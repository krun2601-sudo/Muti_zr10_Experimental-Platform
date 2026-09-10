"""可替换的协同决策层：仅使用检测、射线、估计轨迹和设备遥测。

本模块不导入仿真器，也不读取目标真值。算法输出期望动作，限位、能力
检查和实际执行由控制层负责。内置策略是可解释的研究基线，不代表全局最优。
"""
from __future__ import annotations

import importlib
import itertools
import math
from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable

import numpy as np

from .config import DeviceConfig, LabConfig
from .geometry import intrinsics_at_zoom, project_world_point, project_world_points, world_to_gimbal_angles
from .models import Action, Decision, PolicyContext, Telemetry


@runtime_checkable
class Policy(Protocol):
    """自定义策略唯一必需的接口；reset 在每次实验/学习回合开始时调用。"""

    def reset(self) -> None: ...
    def decide(self, context: PolicyContext) -> Decision: ...


@dataclass(frozen=True)
class _Candidate:
    pair: tuple[str, str]
    targets: tuple[str, ...]
    actions: dict[str, Action]
    quality: float


class HoldPolicy:
    """不修改参数；仍输出可记录的空动作，便于检查完整数据管道。"""

    def __init__(self, cfg: LabConfig):
        self.cfg = cfg
        self.devices = {d.id: d for d in cfg.active_devices}
        self.enabled = frozenset(cfg.action_space.get("enabled", ["yaw_deg", "pitch_deg"]))

    def reset(self) -> None:
        pass

    def _available_ids(self, context: PolicyContext) -> list[str]:
        maximum_age = float(self.cfg.system.get("telemetry_stale_s", .5))
        return sorted(d for d in self.devices if d in context.devices and context.devices[d].connected
                      and 0 <= context.t - context.devices[d].t <= maximum_age
                      # 共同视场候选需要可信的实际倍率。旧固件查询失败或镜头仍在
                      # 变焦时，不能把配置初值当作实际焦距来安排空间扫描/定位。
                      and context.devices[d].raw.get("zoom_known", context.devices[d].source == "simulation")
                      and context.devices[d].raw.get("zoom_stable", context.devices[d].source == "simulation"))

    def decide(self, context: PolicyContext) -> Decision:
        return Decision({k: Action(k, issued_t=context.t) for k in self.devices})

    def _aim(self, device: DeviceConfig, state: Telemetry, points: list[np.ndarray],
             t: float, targets: tuple[str, ...] = (), reason: str = "track") -> Action | None:
        """在单位球面上求视轴中心，并使用真实内参投影验证共同视场。

        两个目标共处视场不等于两目标的三维坐标平均值可见：距离差很大时
        坐标均值会偏向远目标。因此先求各目标的单位方向，再取平均方向。
        冻结轴必须保留当前遥测值参与投影，否则会虚构设备无法实现的视场。
        """
        origin = np.asarray(device.position_m, dtype=float)
        vectors = np.asarray(points) - origin
        lengths = np.linalg.norm(vectors, axis=1)
        if np.any(lengths < 1e-6):
            return None
        direction = np.mean(vectors / lengths[:, None], axis=0)
        if np.linalg.norm(direction) < 1e-8:
            return None
        yaw, pitch = world_to_gimbal_angles(origin + direction, device)
        desired = {"yaw_deg": yaw, "pitch_deg": pitch, "zoom": state.zoom}
        if self.cfg.policy.get("auto_zoom", False) and "zoom" in self.enabled:
            # 保守基线只使用显式配置倍率；高级策略可自己搜索所有标定倍率。
            desired["zoom"] = float(self.cfg.policy.get("tracking_zoom", device.zoom_limits[0]))
        for name, limits in (("yaw_deg", device.yaw_limits_deg),
                             ("pitch_deg", device.pitch_limits_deg), ("zoom", device.zoom_limits)):
            if name not in self.enabled:
                desired[name] = getattr(state, name)
            if not limits[0] <= desired[name] <= limits[1]:
                return None
        future = replace(state, **desired)
        width, height = device.camera.get("image_size", (1920, 1080))
        margin = float(self.cfg.policy.get("fov_margin", 0.06))
        # 多目标一次批量投影，避免对同一候选相机重复解析内参与姿态。
        for pixel in project_world_points(points, future, device):
            if pixel is None:
                return None
            u, v = pixel
            if not (margin * width <= u <= (1 - margin) * width and
                    margin * height <= v <= (1 - margin) * height):
                return None
        return Action(device.id,
                      yaw_deg=desired["yaw_deg"] if "yaw_deg" in self.enabled else None,
                      pitch_deg=desired["pitch_deg"] if "pitch_deg" in self.enabled else None,
                      zoom=desired["zoom"] if "zoom" in self.enabled and self.cfg.policy.get("auto_zoom", False) else None,
                      target_ids=targets, reason=reason, issued_t=t,
                      ttl_s=float(self.cfg.system.get("action_ttl_s", 0.5)))


class ScanPolicy(HoldPolicy):
    """把空闲设备成对瞄准同一个空间网格点，以创造双站发现条件。

    扫描点是配置的空间搜索位置，不是已发现目标。驻留从两台设备都达到
    指向容差时开始计时，因此不会把云台转动时间错误地当作有效观测时间。
    """

    def __init__(self, cfg: LabConfig):
        super().__init__(cfg)
        points = cfg.policy.get("scan_points_m")
        if points is None:
            roi = cfg.policy.get("roi", {"x": [80, 180], "y": [-50, 50], "z": [20, 60]})
            grid = cfg.policy.get("scan_grid", [3, 3, 2])
            axes = [np.linspace(*roi[name], max(1, int(n))) for name, n in zip(("x", "y", "z"), grid)]
            # 蛇形遍历减少相邻扫描点的大幅回扫。
            points = []
            for iz, z in enumerate(axes[2]):
                for iy, y in enumerate(axes[1] if iz % 2 == 0 else axes[1][::-1]):
                    for x in (axes[0] if (iy + iz) % 2 == 0 else axes[0][::-1]):
                        points.append([x, y, z])
        self.scan_points = [np.asarray(p, dtype=float) for p in points]
        if not self.scan_points or any(p.shape != (3,) or not np.isfinite(p).all() for p in self.scan_points):
            raise ValueError("policy.scan_points_m 必须包含有限三维坐标")
        if not 0 <= float(cfg.policy.get("fov_margin", .06)) < .5:
            raise ValueError("policy.fov_margin 必须在 [0, 0.5) 内")
        self.reset()

    def reset(self) -> None:
        self._scan_state: dict[tuple[str, ...], tuple[int, float | None]] = {}

    def _pairs(self, ids: list[str]) -> list[tuple[str, ...]]:
        """优先较长基线；双站几何质量仍在跟踪候选中逐目标评估。"""
        remaining = sorted(ids)
        result = []
        while len(remaining) >= 2:
            pair = max(itertools.combinations(remaining, 2), key=lambda ab: float(np.linalg.norm(
                np.asarray(self.devices[ab[0]].position_m) - self.devices[ab[1]].position_m)))
            result.append(pair)
            remaining = [d for d in remaining if d not in pair]
        if remaining:
            result.append(tuple(remaining))
        return result

    def _scan(self, context: PolicyContext, ids: list[str]) -> dict[str, Action]:
        actions: dict[str, Action] = {}
        for pair_index, pair in enumerate(self._pairs(ids)):
            index, reached_t = self._scan_state.get(pair, (pair_index * max(1, len(self.scan_points) // 2), None))
            # 从当前扫描点向后寻找两台设备共同可达的点；有限循环避免越界配置卡死。
            candidate_actions = None
            for offset in range(len(self.scan_points)):
                point_index = (index + offset) % len(self.scan_points)
                aimed = {d: self._aim(self.devices[d], context.devices[d], [self.scan_points[point_index]],
                                      context.t, reason="paired_scan" if len(pair) == 2 else "scan_auxiliary")
                         for d in pair}
                if all(a is not None for a in aimed.values()):
                    candidate_actions = aimed
                    if offset:
                        reached_t = None
                    index = point_index
                    break
            if candidate_actions is None:
                actions.update({d: Action(d, reason="scan_roi_unreachable", issued_t=context.t) for d in pair})
                continue
            tolerance = float(self.cfg.policy.get("scan_settle_tolerance_deg", 2.0))
            reached = all(abs((a.yaw_deg if a.yaw_deg is not None else context.devices[d].yaw_deg)
                              - context.devices[d].yaw_deg) <= tolerance and
                          abs((a.pitch_deg if a.pitch_deg is not None else context.devices[d].pitch_deg)
                              - context.devices[d].pitch_deg) <= tolerance
                          for d, a in candidate_actions.items())
            if reached:
                reached_t = context.t if reached_t is None else reached_t
                if context.t - reached_t >= float(self.cfg.policy.get("scan_dwell_s", 2.5)):
                    index = (index + 1) % len(self.scan_points)
                    reached_t = None
            else:
                reached_t = None
            self._scan_state[pair] = (index, reached_t)
            actions.update(candidate_actions)
        return actions

    def decide(self, context: PolicyContext) -> Decision:
        ids = self._available_ids(context)
        actions = self._scan(context, ids)
        for d in self.devices:
            actions.setdefault(d, Action(d, reason="unavailable", issued_t=context.t))
        return Decision(actions, {"mode": "paired_scan", "scan_points": len(self.scan_points)})


class CooperativePolicy(ScanPolicy):
    """基于候选设备对和共同视场的有限束搜索分配器。

    覆盖收益只在目标首次取得至少双站指派时计算；几何质量、转动成本、
    切换惩罚和最短驻留约束共同影响分配。同一设备最多属于一个候选组，
    但一个组可以同时看见多个目标。预测仅使用融合轨迹的状态和速度。
    """

    def reset(self) -> None:
        super().reset()
        self._previous: dict[str, tuple[str, ...]] = {}
        self._switched_t: dict[str, float] = {}
        self._candidate_aim_cache = {}
        self._geometry_cache = {}

    def _positions(self, context: PolicyContext) -> dict[str, np.ndarray]:
        timeout = float(self.cfg.policy.get("coast_timeout_s", 2.0))
        horizon = float(self.cfg.policy.get("prediction_horizon_s", .2))
        tracks = sorted((tr for tr in context.tracks if 0 <= context.t - tr.last_seen_t <= timeout),
                        key=lambda tr: (tr.status != "confirmed", -tr.hits, tr.track_id))
        return {tr.track_id: np.asarray(tr.position) + np.asarray(tr.velocity) *
                (max(0.0, context.t - tr.t) + horizon)
                for tr in tracks[:int(self.cfg.policy.get("max_assignment_targets", 8))]}

    def _candidate(self, pair: tuple[str, str], target_ids: tuple[str, ...],
                   points: dict[str, np.ndarray], context: PolicyContext) -> _Candidate | None:
        actions = {}
        quality = 0.0
        active_targets = set(points)
        for d in pair:
            key = (d, target_ids)
            if key in self._candidate_aim_cache:
                cached = self._candidate_aim_cache[key]
                if cached is None:
                    return None
                actions[d], cached_quality = cached
                quality += cached_quality
                continue
            # 同一设备/目标组会出现在多个不同设备对中；投影结果与另一台
            # 设备无关，只计算一次。缓存每周期清空，绝不使用旧遥测的视场。
            self._candidate_aim_cache[key] = None
            quality_before_device = quality
            previous = self._previous.get(d, ())
            changed = bool(previous) and previous != target_ids
            # 旧目标已经超时才解除硬驻留，防止失去目标后永远锁住设备。
            if changed and set(previous).issubset(active_targets) and context.t - self._switched_t.get(d, -math.inf) < float(self.cfg.policy.get("minimum_dwell_s", .8)):
                return None
            action = self._aim(self.devices[d], context.devices[d], [points[k] for k in target_ids],
                               context.t, target_ids)
            if action is None:
                return None
            if self.cfg.policy.get("mode", "multi") == "center":
                # center 模式不能用“目标仍在图像边缘”替代中心跟踪。尤其
                # 当某角度被冻结时，必须验证实际可实现的视轴是否能居中。
                state = context.devices[d]
                future = replace(state,
                                 yaw_deg=state.yaw_deg if action.yaw_deg is None else action.yaw_deg,
                                 pitch_deg=state.pitch_deg if action.pitch_deg is None else action.pitch_deg,
                                 zoom=state.zoom if action.zoom is None else action.zoom)
                camera = intrinsics_at_zoom(self.devices[d], future.zoom)
                pixel = project_world_point(points[target_ids[0]], future, self.devices[d])
                tolerance = math.tan(math.radians(float(self.cfg.policy.get("center_tolerance_deg", .5))))
                if pixel is None or math.hypot((pixel[0] - camera.cx) / camera.fx,
                                               (pixel[1] - camera.cy) / camera.fy) > tolerance:
                    return None
            actions[d] = action
            state = context.devices[d]
            slew = math.hypot((action.yaw_deg if action.yaw_deg is not None else state.yaw_deg) - state.yaw_deg,
                              (action.pitch_deg if action.pitch_deg is not None else state.pitch_deg) - state.pitch_deg)
            quality -= float(self.cfg.policy.get("slew_weight", .12)) * slew / max(self.devices[d].max_slew_dps, 1)
            if changed:
                quality -= float(self.cfg.policy.get("assignment_switch_penalty", .35))
            self._candidate_aim_cache[key] = (action, quality - quality_before_device)
        geometry = []
        for target in target_ids:
            key = (pair, target)
            if key in self._geometry_cache:
                if self._geometry_cache[key] is None:
                    return None
                geometry.append(self._geometry_cache[key])
                continue
            rays = [points[target] - self.devices[d].position_m for d in pair]
            rays = [r / np.linalg.norm(r) for r in rays]
            # 0° 和 180° 都是退化交会，使用锐角描述两条直线的夹角。
            angle = math.degrees(math.acos(float(np.clip(abs(np.dot(*rays)), 0, 1))))
            if angle < float(self.cfg.policy.get("minimum_intersection_deg", 2.0)):
                self._geometry_cache[key] = None
                return None
            self._geometry_cache[key] = math.sin(math.radians(angle))
            geometry.append(self._geometry_cache[key])
        quality += float(self.cfg.policy.get("geometry_weight", .75)) * float(np.mean(geometry))
        return _Candidate(pair, target_ids, actions, quality)

    def _assign(self, ids: list[str], positions: dict[str, np.ndarray], context: PolicyContext) -> list[_Candidate]:
        self._candidate_aim_cache.clear()
        self._geometry_cache.clear()
        mode = self.cfg.policy.get("mode", "multi")
        if mode not in ("center", "multi"):
            raise ValueError("policy.mode 只支持 center / multi")
        group_limit = 1 if mode == "center" else int(self.cfg.policy.get("max_shared_targets", 3))
        groups = [g for n in range(1, min(group_limit, len(positions)) + 1)
                  for g in itertools.combinations(sorted(positions), n)]
        candidates: list[_Candidate] = []
        keep = int(self.cfg.policy.get("candidates_per_pair", 8))
        reward = float(self.cfg.policy.get("coverage_weight", 3.0))
        for pair in itertools.combinations(sorted(ids), 2):
            feasible = [c for g in groups if (c := self._candidate(pair, g, positions, context)) is not None]
            feasible.sort(key=lambda c: reward * len(c.targets) + c.quality, reverse=True)
            candidates.extend(feasible[:keep])
        # 状态为 (得分，已处理设备，已有双站覆盖的目标，候选序列)。束宽使
        # 任意设备数量下的运行时间有上界；研究算法可替换成 ILP/MPC/RL。
        beam = [(0.0, frozenset(), frozenset(), [])]
        for _ in ids:
            expanded = []
            for score, used, covered, selected in beam:
                remaining = [d for d in ids if d not in used]
                if not remaining:
                    expanded.append((score, used, covered, selected))
                    continue
                first = remaining[0]
                expanded.append((score, used | {first}, covered, selected))
                for candidate in candidates:
                    if first not in candidate.pair or used.intersection(candidate.pair):
                        continue
                    new = set(candidate.targets) - covered
                    # 对已经覆盖的同一目标仅给少量冗余观测奖励，防止全部
                    # 设备追一个目标而忽略能够形成第二组双站定位的新目标。
                    gain = reward * len(new) + .05 * (len(candidate.targets) - len(new)) + candidate.quality
                    expanded.append((score + gain, used | set(candidate.pair),
                                     covered | set(candidate.targets), selected + [candidate]))
            expanded.sort(key=lambda row: row[0], reverse=True)
            beam = expanded[:max(1, int(self.cfg.policy.get("assignment_beam_width", 64)))]
        return max(beam, key=lambda row: row[0])[3]

    def _search_rays(self, context: PolicyContext, ids: list[str], positions: dict[str, np.ndarray]):
        """用单站方向和假设距离引导另一站；从不把假设写成 Track/Localization。"""
        actions, hypotheses = {}, []
        distance = float(self.cfg.policy.get("ray_search_distance_m", 150.0))
        ttl = float(self.cfg.policy.get("search_hypothesis_ttl_s", 1.5))
        if distance <= 0:
            return actions, hypotheses
        for ray in sorted(context.rays, key=lambda r: (-r.confidence, -r.t, r.detection_id)):
            if ray.device_id not in ids or ray.device_id in actions or not 0 <= context.t - ray.t <= ttl:
                continue
            direction = np.asarray(ray.direction, dtype=float)
            length = np.linalg.norm(direction)
            if length < 1e-9:
                continue
            direction /= length
            # 已有轨迹方向附近的射线不重复启动假设搜索。
            if any(np.dot((p - ray.origin) / np.linalg.norm(p - ray.origin), direction) > math.cos(math.radians(3))
                   for p in positions.values() if np.linalg.norm(p - ray.origin) > 1e-6):
                continue
            point = np.asarray(ray.origin) + direction * distance
            source = self._aim(self.devices[ray.device_id], context.devices[ray.device_id], [point], context.t, reason="search_hypothesis")
            if source is None:
                continue
            other_ids = [d for d in ids if d != ray.device_id and d not in actions]
            other_ids.sort(key=lambda d: -float(np.linalg.norm(np.asarray(self.devices[d].position_m) - ray.origin)))
            for other in other_ids:
                second = self._aim(self.devices[other], context.devices[other], [point], context.t, reason="search_hypothesis")
                if second is not None:
                    actions.update({ray.device_id: source, other: second})
                    hypotheses.append({"source_detection_id": ray.detection_id, "device_ids": [ray.device_id, other],
                                       "assumed_position_m": point.tolist(), "assumed_range_m": distance,
                                       "is_localization": False, "reason": "single_station_range_assumption"})
                    break
        return actions, hypotheses

    def decide(self, context: PolicyContext) -> Decision:
        ids = self._available_ids(context)
        positions = self._positions(context)
        assignments = self._assign(ids, positions, context) if positions else []
        actions = {d: action for candidate in assignments for d, action in candidate.actions.items()}
        free = [d for d in ids if d not in actions]
        search, hypotheses = self._search_rays(context, free, positions)
        actions.update(search)
        actions.update(self._scan(context, [d for d in free if d not in search]))
        for d in self.devices:
            actions.setdefault(d, Action(d, reason="unavailable", issued_t=context.t))
            targets = actions[d].target_ids
            if targets != self._previous.get(d, ()):
                self._switched_t[d] = context.t
            self._previous[d] = targets
        covered = sorted({k for c in assignments for k in c.targets})
        return Decision(actions, {"mode": self.cfg.policy.get("mode", "multi"),
                                  "covered_track_ids": covered,
                                  "assignments": [{"devices": list(c.pair), "targets": list(c.targets),
                                                   "quality": c.quality} for c in assignments],
                                  "search_hypotheses": hypotheses,
                                  "unassigned_track_ids": sorted(set(positions) - set(covered))})


def build_policy(cfg: LabConfig) -> Policy:
    """创建策略；custom 指向本地 Python 的 ``模块名:类名``，构造器接收 cfg。"""
    name = str(cfg.policy.get("name", cfg.policy.get("type", "cooperative")))
    builtins = {"cooperative": CooperativePolicy, "scan": ScanPolicy, "hold": HoldPolicy}
    if name in builtins:
        return builtins[name](cfg)
    spec = cfg.policy.get("custom", cfg.policy.get("class_path", "")) if name == "custom" else name
    if not isinstance(spec, str) or ":" not in spec:
        raise ValueError(f"未知策略 {name!r}；自定义策略使用 module:Class")
    module, class_name = spec.rsplit(":", 1)
    instance = getattr(importlib.import_module(module), class_name)(cfg)
    if not isinstance(instance, Policy):
        raise TypeError("自定义策略必须实现 reset() 和 decide(context)")
    return instance
