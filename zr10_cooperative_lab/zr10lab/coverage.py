"""统一的多固定光电设备覆盖问题与严格覆盖跟踪器。

本模块是所有覆盖算法共享的唯一几何/时间模型。算法只能读取 CoverageProblem
和 PolicyContext.coverage，不得自行建立另一套 FoV 判定。这里不导入 simulation、
hardware、SDK 或 vision，也不接触任何目标真值。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import product
import hashlib
import json
import math
from typing import Any, Iterable, Sequence

import numpy as np

from .config import DeviceConfig, LabConfig
from .geometry import intrinsics_at_zoom, project_world_points, world_to_gimbal_angles
from .models import CoverageSnapshot, Telemetry


class CoverageConfigurationError(ValueError):
    """覆盖问题配置或几何不可行。"""


@dataclass(frozen=True)
class CandidateViewpoint:
    viewpoint_id: str
    device_id: str
    aim_point_m: tuple[float, float, float]
    yaw_deg: float
    pitch_deg: float
    zoom: float
    covered_cell_ids: tuple[int, ...]


@dataclass(frozen=True)
class CoverageCellRecord:
    cell_id: int
    position_m: tuple[float, float, float]
    first_covered_t_s: float
    device_ids: tuple[str, ...]
    viewpoint_ids: tuple[str, ...]
    required_views: int = 1


def _grid_points(roi: dict[str, Any], grid: Sequence[int], name: str) -> np.ndarray:
    if len(grid) != 3 or any(isinstance(n, bool) or int(n) != n or int(n) < 1 for n in grid):
        raise CoverageConfigurationError(f"{name} 必须为三个正整数 [nx, ny, nz]")
    axes = []
    for axis, count in zip(("x", "y", "z"), grid):
        bounds = roi.get(axis)
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            raise CoverageConfigurationError(f"policy.roi.{axis} 必须为 [min,max]")
        low, high = map(float, bounds)
        if not all(math.isfinite(v) for v in (low, high)) or low >= high:
            raise CoverageConfigurationError(f"policy.roi.{axis} 范围不合法")
        axes.append(np.linspace(low, high, int(count), dtype=float))
    return np.asarray(list(product(*axes)), dtype=float)


def _angle_delta_deg(a: float, b: float) -> float:
    """本地云台不是循环无限轴，采用数值差，不跨限位做 360° 捷径。"""
    return abs(float(a) - float(b))


class CoverageProblem:
    """所有算法共享的离散覆盖问题。

    evaluation_cells_m 是严格评价网格；candidate aim points 只用于生成可执行的
    观测姿态。覆盖矩阵完全由 project_world_points、实际内参、安装姿态和固定
    zoom 计算。问题 hash 不包含 algorithm_id/seed，因此同一场景的不同算法必须
    得到相同 hash。
    """

    VERSION = "coverage-problem-v1"

    def __init__(self, cfg: LabConfig):
        self.cfg = cfg
        self.devices: dict[str, DeviceConfig] = {d.id: d for d in cfg.active_devices}
        self.device_ids = tuple(sorted(self.devices))
        self.options = dict(cfg.policy.get("coverage", {}))
        if not self.options.get("enabled", False):
            raise CoverageConfigurationError("policy.coverage.enabled=true 才能建立严格覆盖问题")
        self.roi = cfg.policy.get("roi", {})
        self.evaluation_grid = tuple(int(x) for x in self.options.get("evaluation_grid", [5, 5, 3]))
        self.candidate_grid = tuple(int(x) for x in self.options.get("candidate_grid", [4, 4, 2]))
        self.cells_m = _grid_points(self.roi, self.evaluation_grid, "evaluation_grid")
        self.candidate_aim_points_m = _grid_points(self.roi, self.candidate_grid, "candidate_grid")
        self.cell_ids = tuple(range(len(self.cells_m)))
        self.fixed_zoom = float(self.options.get("fixed_zoom", min(d.initial_zoom for d in self.devices.values())))
        self.fov_margin = float(self.options.get("fov_margin", cfg.policy.get("fov_margin", .06)))
        self.effective_range_m = float(self.options.get("effective_range_m", math.inf))
        self.dwell_s = float(self.options.get("dwell_s", .5))
        self.settle_s = float(self.options.get("settle_s", .2))
        self.settle_rate_dps = float(self.options.get("settle_rate_dps", .5))
        self.completion_threshold = float(self.options.get("completion_threshold", 1.0))
        self.telemetry_stale_s = float(cfg.system.get("telemetry_stale_s", .5))
        self.min_target_pixels = float(self.options.get("min_target_pixels", 0.0))
        self.target_reference_size_m = float(self.options.get("target_reference_size_m", 0.0))
        self.redundancy_threshold = float(self.options.get("redundancy_threshold", 0.995))
        self.required_views = int(self.options.get("required_views", 1))
        self.open_path = bool(self.options.get("open_path", True))
        self._validate_options()

        self.initial_pose: dict[str, tuple[float, float, float]] = {
            d.id: (float(d.initial_yaw_deg), float(d.initial_pitch_deg), float(d.initial_zoom))
            for d in cfg.active_devices
        }
        self.viewpoints_by_device: dict[str, tuple[CandidateViewpoint, ...]] = {}
        self.viewpoint_lookup: dict[str, CandidateViewpoint] = {}
        self.coverage_masks: dict[str, np.ndarray] = {}
        self.transition_cost_s: dict[str, np.ndarray] = {}
        self.initial_transition_s: dict[str, np.ndarray] = {}
        self._build_viewpoints()
        self._build_transition_costs()

        reachable_counts = np.zeros(len(self.cells_m), dtype=int)
        for d in self.device_ids:
            masks = self.coverage_masks[d]
            if len(masks):
                reachable_counts += np.any(masks, axis=0).astype(int)
        self.unreachable_cell_ids = tuple(int(i) for i in np.flatnonzero(reachable_counts < self.required_views))
        self.problem_hash = self._make_hash()

    def _validate_options(self) -> None:
        if not 0 <= self.fov_margin < .5:
            raise CoverageConfigurationError("coverage.fov_margin 必须在 [0,0.5) 内")
        positive = {
            "effective_range_m": self.effective_range_m,
            "dwell_s": self.dwell_s,
            "settle_s": self.settle_s,
            "settle_rate_dps": self.settle_rate_dps,
        }
        for name, value in positive.items():
            if not math.isfinite(value) or value < 0 or (name in ("effective_range_m", "settle_rate_dps") and value <= 0):
                raise CoverageConfigurationError(f"coverage.{name} 不合法")
        if not 0 < self.completion_threshold <= 1:
            raise CoverageConfigurationError("coverage.completion_threshold 必须在 (0,1] 内")
        if not 0 <= self.redundancy_threshold <= 1:
            raise CoverageConfigurationError("coverage.redundancy_threshold 必须在 [0,1] 内")
        if self.required_views < 1:
            raise CoverageConfigurationError("coverage.required_views 必须为正整数")
        if self.min_target_pixels < 0 or self.target_reference_size_m < 0:
            raise CoverageConfigurationError("最低目标像素/参考尺寸不能为负")
        for d in self.devices.values():
            if not d.zoom_limits[0] <= self.fixed_zoom <= d.zoom_limits[1]:
                raise CoverageConfigurationError(f"{d.id}: fixed_zoom={self.fixed_zoom} 超出倍率限位")
            intrinsics_at_zoom(d, self.fixed_zoom)

    def assert_feasible(self) -> None:
        if self.unreachable_cell_ids:
            sample = list(self.unreachable_cell_ids[:12])
            suffix = "..." if len(self.unreachable_cell_ids) > len(sample) else ""
            raise CoverageConfigurationError(
                f"严格覆盖问题存在 {len(self.unreachable_cell_ids)} 个不可达单元: {sample}{suffix}；"
                "请检查ROI、候选网格、FoV/倍率、安装外参、机械限位或effective_range_m")

    def _future_state(self, device: DeviceConfig, yaw: float, pitch: float) -> Telemetry:
        return Telemetry(device.id, 0.0, yaw, pitch, zoom=self.fixed_zoom, connected=True,
                         source="simulation", raw={"zoom_known": True, "zoom_stable": True})

    def _coverage_for_pose(self, device: DeviceConfig, yaw: float, pitch: float) -> tuple[int, ...]:
        state = self._future_state(device, yaw, pitch)
        intr = intrinsics_at_zoom(device, self.fixed_zoom)
        pixels = project_world_points(self.cells_m, state, device)
        origin = np.asarray(device.position_m, dtype=float)
        ranges = np.linalg.norm(self.cells_m - origin, axis=1)
        ids: list[int] = []
        for m, pixel in enumerate(pixels):
            if pixel is None or ranges[m] > self.effective_range_m:
                continue
            u, v = pixel
            if not (self.fov_margin * intr.width <= u <= (1.0 - self.fov_margin) * intr.width and
                    self.fov_margin * intr.height <= v <= (1.0 - self.fov_margin) * intr.height):
                continue
            if self.min_target_pixels > 0:
                if self.target_reference_size_m <= 0:
                    raise CoverageConfigurationError("启用 min_target_pixels 时必须配置 target_reference_size_m")
                pixels_per_target = min(intr.fx, intr.fy) * self.target_reference_size_m / max(ranges[m], 1e-9)
                if pixels_per_target < self.min_target_pixels:
                    continue
            ids.append(m)
        return tuple(ids)

    def _build_viewpoints(self) -> None:
        for device_id in self.device_ids:
            d = self.devices[device_id]
            raw: list[CandidateViewpoint] = []
            for k, point in enumerate(self.candidate_aim_points_m):
                yaw, pitch = world_to_gimbal_angles(point, d)
                if not (d.yaw_limits_deg[0] <= yaw <= d.yaw_limits_deg[1] and
                        d.pitch_limits_deg[0] <= pitch <= d.pitch_limits_deg[1]):
                    continue
                covered = self._coverage_for_pose(d, yaw, pitch)
                if not covered:
                    continue
                raw.append(CandidateViewpoint(
                    viewpoint_id=f"{device_id}:vp{k:04d}", device_id=device_id,
                    aim_point_m=tuple(float(x) for x in point), yaw_deg=float(yaw),
                    pitch_deg=float(pitch), zoom=self.fixed_zoom, covered_cell_ids=covered))
            kept: list[CandidateViewpoint] = []
            # 只删除不会增加任何覆盖能力的高度冗余姿态，避免为了降维破坏可达性。
            for vp in sorted(raw, key=lambda x: (len(x.covered_cell_ids), x.viewpoint_id), reverse=True):
                s = set(vp.covered_cell_ids)
                redundant = False
                for old in kept:
                    o = set(old.covered_cell_ids)
                    union = len(s | o)
                    jaccard = len(s & o) / max(union, 1)
                    if s <= o and jaccard >= self.redundancy_threshold:
                        redundant = True
                        break
                if not redundant:
                    kept.append(vp)
            kept.sort(key=lambda x: x.viewpoint_id)
            self.viewpoints_by_device[device_id] = tuple(kept)
            for vp in kept:
                self.viewpoint_lookup[vp.viewpoint_id] = vp
            masks = np.zeros((len(kept), len(self.cells_m)), dtype=bool)
            for r, vp in enumerate(kept):
                masks[r, list(vp.covered_cell_ids)] = True
            self.coverage_masks[device_id] = masks

    def _slew_time(self, device: DeviceConfig, yaw0: float, pitch0: float, yaw1: float, pitch1: float) -> float:
        dy = _angle_delta_deg(yaw1, yaw0)
        dp = _angle_delta_deg(pitch1, pitch0)
        table = self.options.get("measured_slew_table", [])
        if table:
            rows = sorted((float(row["angle_deg"]), float(row["time_s"])) for row in table)
            if any(a < 0 or t < 0 or not math.isfinite(a + t) for a, t in rows):
                raise CoverageConfigurationError("measured_slew_table 必须包含非负有限 angle_deg/time_s")
            # 实测表以 max(|dYaw|,|dPitch|) 为自变量；超表范围线性外推会不安全，故夹持到端点。
            angle = max(dy, dp)
            return float(np.interp(angle, [x[0] for x in rows], [x[1] for x in rows]))
        yaw_rate = float(self.options.get("yaw_rate_dps", device.control.get("yaw_speed_limit", device.max_slew_dps)))
        pitch_rate = float(self.options.get("pitch_rate_dps", device.control.get("pitch_speed_limit", device.max_slew_dps)))
        if min(yaw_rate, pitch_rate) <= 0:
            raise CoverageConfigurationError("yaw_rate_dps/pitch_rate_dps 必须为正")
        return max(dy / yaw_rate, dp / pitch_rate)

    def transition_time(self, device_id: str, yaw0: float, pitch0: float, yaw1: float, pitch1: float) -> float:
        d = self.devices[device_id]
        return self._slew_time(d, yaw0, pitch0, yaw1, pitch1) + self.settle_s + self.dwell_s

    def _build_transition_costs(self) -> None:
        for device_id in self.device_ids:
            vps = self.viewpoints_by_device[device_id]
            n = len(vps)
            matrix = np.zeros((n, n), dtype=float)
            for r, a in enumerate(vps):
                for s, b in enumerate(vps):
                    if r != s:
                        matrix[r, s] = self.transition_time(device_id, a.yaw_deg, a.pitch_deg, b.yaw_deg, b.pitch_deg)
            self.transition_cost_s[device_id] = matrix
            y0, p0, _ = self.initial_pose[device_id]
            self.initial_transition_s[device_id] = np.asarray([
                self.transition_time(device_id, y0, p0, vp.yaw_deg, vp.pitch_deg) for vp in vps
            ], dtype=float)

    def viewpoint_index(self, device_id: str, viewpoint_id: str) -> int:
        for i, vp in enumerate(self.viewpoints_by_device[device_id]):
            if vp.viewpoint_id == viewpoint_id:
                return i
        raise KeyError(viewpoint_id)

    def route_cost(self, device_id: str, route: Sequence[str]) -> float:
        if not route:
            return 0.0
        indices = [self.viewpoint_index(device_id, x) for x in route]
        cost = float(self.initial_transition_s[device_id][indices[0]])
        matrix = self.transition_cost_s[device_id]
        cost += sum(float(matrix[a, b]) for a, b in zip(indices, indices[1:]))
        if not self.open_path and len(indices):
            last = self.viewpoints_by_device[device_id][indices[-1]]
            y0, p0, _ = self.initial_pose[device_id]
            cost += self.transition_time(device_id, last.yaw_deg, last.pitch_deg, y0, p0)
        return cost

    def route_coverage_mask(self, routes: dict[str, Sequence[str]]) -> np.ndarray:
        mask = np.zeros(len(self.cells_m), dtype=bool)
        for route in routes.values():
            for vid in route:
                mask[list(self.viewpoint_lookup[vid].covered_cell_ids)] = True
        return mask

    def route_makespan(self, routes: dict[str, Sequence[str]]) -> float:
        return max((self.route_cost(d, routes.get(d, ())) for d in self.device_ids), default=0.0)

    def candidates_covering(self, device_id: str, cell_id: int) -> tuple[CandidateViewpoint, ...]:
        return tuple(vp for vp in self.viewpoints_by_device[device_id] if cell_id in vp.covered_cell_ids)

    def nearest_viewpoint_id(self, device_id: str, state: Telemetry, tolerance_deg: float = 2.0) -> str | None:
        best = None
        best_error = math.inf
        for vp in self.viewpoints_by_device.get(device_id, ()):
            error = math.hypot(vp.yaw_deg - state.yaw_deg, vp.pitch_deg - state.pitch_deg)
            if error < best_error:
                best, best_error = vp.viewpoint_id, error
        return best if best_error <= tolerance_deg else None

    def _make_hash(self) -> str:
        payload: dict[str, Any] = {
            "version": self.VERSION,
            "roi": self.roi,
            "evaluation_grid": self.evaluation_grid,
            "candidate_grid": self.candidate_grid,
            "fixed_zoom": self.fixed_zoom,
            "fov_margin": self.fov_margin,
            "effective_range_m": self.effective_range_m,
            "dwell_s": self.dwell_s,
            "settle_s": self.settle_s,
            "settle_rate_dps": self.settle_rate_dps,
            "required_views": self.required_views,
            "open_path": self.open_path,
            "cells": np.round(self.cells_m, 8).tolist(),
            "devices": {},
        }
        for did in self.device_ids:
            d = self.devices[did]
            payload["devices"][did] = {
                "position": list(map(float, d.position_m)),
                "mount": list(map(float, d.mount_rpy_deg)),
                "limits": [list(map(float, d.yaw_limits_deg)), list(map(float, d.pitch_limits_deg))],
                "initial": list(map(float, self.initial_pose[did])),
                "viewpoints": [{
                    "id": vp.viewpoint_id, "aim": list(vp.aim_point_m), "yaw": round(vp.yaw_deg, 8),
                    "pitch": round(vp.pitch_deg, 8), "covered": list(vp.covered_cell_ids)
                } for vp in self.viewpoints_by_device[did]],
                "initial_cost": np.round(self.initial_transition_s[did], 8).tolist(),
                "transition": np.round(self.transition_cost_s[did], 8).tolist(),
            }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class CoverageTracker:
    """根据真实 Telemetry 维护严格覆盖；算法只能读取不可变 snapshot。

    一个 cell 必须由同一设备连续满足健康、固定倍率、低角速度、FoV margin、
    range 条件至少 settle_s+dwell_s 后才记为首次有效覆盖。瞬时覆盖率不要求
    settle/dwell，用于诊断。覆盖判定与目标检测/仿真真值完全无关。
    """

    def __init__(self, problem: CoverageProblem):
        problem.assert_feasible()
        self.problem = problem
        n_dev, n_cell = len(problem.device_ids), len(problem.cells_m)
        self._device_index = {d: i for i, d in enumerate(problem.device_ids)}
        self.visited_mask = np.zeros(n_cell, dtype=bool)
        self.first_covered_times = np.full(n_cell, np.nan, dtype=float)
        self._valid_since = np.full((n_dev, n_cell), np.nan, dtype=float)
        self._previous_states: dict[str, Telemetry] = {}
        self._new_records: list[CoverageCellRecord] = []
        self.newly_covered_ids: tuple[int, ...] = ()
        self.start_t: float | None = None
        self.completion_time_s: float | None = None
        self.instant_fraction = 0.0
        self._overlap_numerator = 0.0
        self._overlap_denominator = 0.0
        self.slew_cost = 0.0
        self.device_active_s = {d: 0.0 for d in problem.device_ids}
        self._last_t: float | None = None

    def _healthy(self, t: float, state: Telemetry | None) -> bool:
        if state is None or not state.connected or not math.isfinite(state.t):
            return False
        if not 0 <= t - state.t <= self.problem.telemetry_stale_s:
            return False
        simulated = state.source == "simulation"
        if not state.raw.get("zoom_known", simulated):
            return False
        if not state.raw.get("zoom_stable", simulated):
            return False
        if abs(float(state.zoom) - self.problem.fixed_zoom) > float(self.problem.options.get("zoom_tolerance", .05)):
            return False
        if math.hypot(state.yaw_rate_dps, state.pitch_rate_dps) > self.problem.settle_rate_dps:
            return False
        return True

    def _visible_mask(self, device: DeviceConfig, state: Telemetry) -> np.ndarray:
        intr = intrinsics_at_zoom(device, state.zoom)
        pixels = project_world_points(self.problem.cells_m, state, device)
        ranges = np.linalg.norm(self.problem.cells_m - np.asarray(device.position_m, dtype=float), axis=1)
        mask = np.zeros(len(self.problem.cells_m), dtype=bool)
        for m, pixel in enumerate(pixels):
            if pixel is None or ranges[m] > self.problem.effective_range_m:
                continue
            u, v = pixel
            if not (self.problem.fov_margin * intr.width <= u <= (1 - self.problem.fov_margin) * intr.width and
                    self.problem.fov_margin * intr.height <= v <= (1 - self.problem.fov_margin) * intr.height):
                continue
            if self.problem.min_target_pixels > 0:
                px = min(intr.fx, intr.fy) * self.problem.target_reference_size_m / max(ranges[m], 1e-9)
                if px < self.problem.min_target_pixels:
                    continue
            mask[m] = True
        return mask

    def update(self, t: float, states: dict[str, Telemetry]) -> CoverageSnapshot:
        if self.start_t is None:
            self.start_t = float(t)
        dt = 0.0 if self._last_t is None else max(0.0, float(t) - self._last_t)
        self._last_t = float(t)
        self._new_records = []
        instant_counts = np.zeros(len(self.problem.cells_m), dtype=int)
        effective_counts = np.zeros(len(self.problem.cells_m), dtype=int)
        effective_by_cell: dict[int, list[str]] = {}

        for did in self.problem.device_ids:
            state = states.get(did)
            previous = self._previous_states.get(did)
            if state is not None and previous is not None:
                self.slew_cost += math.hypot(state.yaw_deg - previous.yaw_deg, state.pitch_deg - previous.pitch_deg)
            if state is not None:
                self._previous_states[did] = state
            row = self._device_index[did]
            if not self._healthy(t, state):
                self._valid_since[row, :] = np.nan
                continue
            assert state is not None
            visible = self._visible_mask(self.problem.devices[did], state)
            instant_counts += visible.astype(int)
            self.device_active_s[did] += dt if np.any(visible) else 0.0
            starts = self._valid_since[row]
            starts[~visible] = np.nan
            just_visible = visible & np.isnan(starts)
            starts[just_visible] = t
            mature = visible & ((t - starts) + 1e-12 >= self.problem.settle_s + self.problem.dwell_s)
            effective_counts += mature.astype(int)
            for m in np.flatnonzero(mature):
                effective_by_cell.setdefault(int(m), []).append(did)

        self.instant_fraction = float(np.mean(instant_counts >= self.problem.required_views))
        mature_any = effective_counts >= self.problem.required_views
        new = mature_any & ~self.visited_mask
        elapsed = float(t - self.start_t)
        new_ids = tuple(int(i) for i in np.flatnonzero(new))
        for m in new_ids:
            self.first_covered_times[m] = elapsed
            devices = tuple(sorted(effective_by_cell.get(m, ())))
            viewpoint_ids = tuple(filter(None, (
                self.problem.nearest_viewpoint_id(d, states[d], float(self.problem.options.get("viewpoint_match_tolerance_deg", 2.0)))
                for d in devices if d in states
            )))
            self._new_records.append(CoverageCellRecord(
                cell_id=m, position_m=tuple(float(x) for x in self.problem.cells_m[m]),
                first_covered_t_s=elapsed, device_ids=devices,
                viewpoint_ids=viewpoint_ids, required_views=self.problem.required_views))
        self.visited_mask |= new
        self.newly_covered_ids = new_ids
        # inter-device 空间重复：对同一时刻成熟有效的 cell-device 暴露进行积分。
        if np.any(effective_counts):
            self._overlap_numerator += float(np.sum(np.maximum(effective_counts - self.problem.required_views, 0))) * max(dt, 1e-9)
            self._overlap_denominator += float(np.sum(effective_counts)) * max(dt, 1e-9)
        fraction = float(np.mean(self.visited_mask))
        complete = fraction + 1e-12 >= self.problem.completion_threshold
        if complete and self.completion_time_s is None:
            self.completion_time_s = elapsed
        return self.snapshot()

    def snapshot(self) -> CoverageSnapshot:
        fraction = float(np.mean(self.visited_mask)) if len(self.visited_mask) else 1.0
        return CoverageSnapshot(
            problem_hash=self.problem.problem_hash,
            visited_mask=tuple(bool(x) for x in self.visited_mask),
            first_covered_times=tuple(None if not math.isfinite(float(x)) else float(x) for x in self.first_covered_times),
            newly_covered_ids=self.newly_covered_ids,
            fraction=fraction,
            instant_fraction=float(self.instant_fraction),
            complete=bool(fraction + 1e-12 >= self.problem.completion_threshold),
            completion_time_s=self.completion_time_s,
        )

    @property
    def new_records(self) -> tuple[CoverageCellRecord, ...]:
        return tuple(self._new_records)

    def metrics(self) -> dict[str, float | bool | int | None]:
        finite = self.first_covered_times[np.isfinite(self.first_covered_times)]
        workload = np.asarray(list(self.device_active_s.values()), dtype=float)
        return {
            "coverage_fraction": float(np.mean(self.visited_mask)),
            "coverage_instant_fraction": float(self.instant_fraction),
            "coverage_new_cells": int(len(self.newly_covered_ids)),
            "coverage_complete": bool(self.snapshot().complete),
            "coverage_completion_time_s": self.completion_time_s,
            "coverage_mean_first_time_s": float(np.mean(finite)) if len(finite) else None,
            "coverage_p95_first_time_s": float(np.percentile(finite, 95)) if len(finite) else None,
            "coverage_overlap_ratio": self._overlap_numerator / self._overlap_denominator if self._overlap_denominator else 0.0,
            "coverage_slew_cost": float(self.slew_cost),
            "coverage_workload_std": float(np.std(workload)) if len(workload) else 0.0,
        }
