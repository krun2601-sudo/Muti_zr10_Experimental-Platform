"""多站几何关联、空间定位和持续轨迹滤波。

识别类别只用于排除不兼容类别，不作为跨相机目标身份。本模块完全
不接触仿真真值。有限预算的几何假设生成、轨迹预测门控和观测互斥
构成一个可解释基线；拥挤/交叉目标仍可能产生身份歧义，诊断会显式
记录这些情况。可替换为 JPDA/MHT 或带外观特征的学习关联器。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations, product
from typing import Any, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment

from .geometry import triangulate_rays
from .models import Localization, Ray, Track


@dataclass
class _Filter:
    """内部 CV 状态顺序为 [x,y,z,vx,vy,vz]，不暴露可变数组给策略。"""

    track_id: str
    x: np.ndarray
    p: np.ndarray
    t: float
    last_seen_t: float
    hits: int
    class_id: int
    device_ids: tuple[str, ...]


@dataclass
class _Candidate:
    localization: Localization
    rays: tuple[Ray, ...]
    keys: frozenset[tuple[str, str]]
    quality: float


def _key(ray: Ray) -> tuple[str, str]:
    return ray.device_id, ray.detection_id


def _ray_angle_deg(ray: Ray, position: np.ndarray) -> float:
    delta = position - np.asarray(ray.origin)
    length = np.linalg.norm(delta)
    direction = np.asarray(ray.direction, dtype=float)
    norm = np.linalg.norm(direction)
    if length < 1e-9 or norm < 1e-9:
        return float("inf")
    return float(np.rad2deg(np.arccos(np.clip(np.dot(delta, direction) / (length * norm), -1, 1))))


class FusionEngine:
    """可在仿真、实机和 CSV 回放中共用的融合器。

    ``update(rays, t)`` 的 t 必须单调不减，所有时间来自同一会话单调
    时钟。输入可以只含新检测；短时未匹配射线会保留在缓冲区。重复
    detection_id 不会让同一帧被重复定位或虚增轨迹命中次数。
    """

    def __init__(self, options: dict[str, Any] | None = None):
        self.options = dict(options or {})
        for name in ("max_hypotheses", "max_pair_evaluations", "max_rays", "confirmation_hits"):
            if name in self.options:
                value = self.options[name]
                if not isinstance(value, (int, float)) or not np.isfinite(value) or int(value) != value or value < 1:
                    raise ValueError(f"fusion.{name} 必须为正整数")
        for name in ("max_time_skew_s", "max_condition_number", "max_residual_m", "max_range_m",
                     "measurement_floor_m", "track_gate_mahalanobis", "track_gate_distance_m",
                     "track_timeout_s", "max_measurement_age_s", "initial_velocity_std_mps"):
            if name in self.options and (not np.isfinite(float(self.options[name])) or float(self.options[name]) <= 0):
                raise ValueError(f"fusion.{name} 必须为有限正数")
        for name in ("max_time_uncertainty_s", "max_target_speed_mps", "process_accel_std_mps2",
                     "birth_merge_distance_m", "ambiguity_margin", "ambiguity_distance_m"):
            if name in self.options and (not np.isfinite(float(self.options[name])) or float(self.options[name]) < 0):
                raise ValueError(f"fusion.{name} 必须为有限非负数")
        self._tracks: dict[str, _Filter] = {}
        self._buffer: dict[tuple[str, str], Ray] = {}
        self._seen: dict[tuple[str, str], float] = {}
        self._next_id = 1
        self._last_t: float | None = None

    def reset(self) -> None:
        """开始独立试验/回合时清空关联记忆；同一会话中不要随意调用。"""
        self._tracks.clear()
        self._buffer.clear()
        self._seen.clear()
        self._next_id = 1
        self._last_t = None

    def _predict(self, track: _Filter, t: float) -> None:
        dt = t - track.t
        if dt < 0:
            raise ValueError("融合时间倒退，不能直接更新已经预测到未来的轨迹")
        transition = np.eye(6)
        transition[:3, 3:] = np.eye(3) * dt
        # 每个采样间隔采用未知恒加速度噪声。单位为 m/s²。
        gain = np.vstack((np.eye(3) * dt ** 2 / 2, np.eye(3) * dt))
        accel = float(self.options.get("process_accel_std_mps2", 3.0))
        track.x = transition @ track.x
        track.p = transition @ track.p @ transition.T + gain @ gain.T * accel ** 2
        track.p = (track.p + track.p.T) / 2
        track.t = t

    def _compatible(self, left: Ray, right: Ray) -> bool:
        if left.device_id == right.device_id or left.class_id != right.class_id:
            return False
        # 外观向量是可选观测特征，不能用 detection/local_id 代替它。
        if left.embedding is not None and right.embedding is not None:
            a, b = np.asarray(left.embedding), np.asarray(right.embedding)
            if a.shape != b.shape or a.ndim != 1 or not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
                return False
            norm = np.linalg.norm(a) * np.linalg.norm(b)
            if norm > 1e-9:
                distance = 1 - np.clip(float(np.dot(a, b) / norm), -1, 1)
                if distance > float(self.options.get("appearance_cosine_gate", .4)):
                    return False
        return True

    def _candidate(self, rays: Sequence[Ray], rejected: Counter) -> _Candidate | None:
        try:
            localization = triangulate_rays(rays, self.options)
        except (ValueError, np.linalg.LinAlgError) as exc:
            rejected[str(exc).split(":", 1)[0]] += 1
            return None
        # 多站支持优先，其次考虑交会残差。该分数用于排序而非概率。
        scale = max(float(self.options.get("max_residual_m", 3.0)), 1e-6)
        quality = localization.residual_m / scale - .5 * (len(rays) - 2)
        quality += .05 * (1 - float(np.mean([r.confidence for r in rays])))
        return _Candidate(localization, tuple(rays), frozenset(_key(r) for r in rays), quality)

    def _make_candidates(self, rays: list[Ray], rejected: Counter) -> tuple[list[_Candidate], bool]:
        groups: dict[str, list[Ray]] = {}
        for ray in rays:
            groups.setdefault(ray.device_id, []).append(ray)
        for group in groups.values():
            group.sort(key=lambda r: (-r.confidence, -r.t, r.detection_id))
        candidates: dict[frozenset[tuple[str, str]], _Candidate] = {}
        limit = int(self.options.get("max_hypotheses", 300))
        pair_limit = int(self.options.get("max_pair_evaluations", 2000))
        pair_count, truncated = 0, False
        stations = sorted(groups)
        for left, right in combinations(stations, 2):
            for a, b in product(groups[left], groups[right]):
                pair_count += 1
                if pair_count > pair_limit or len(candidates) >= limit:
                    truncated = True
                    break
                if not self._compatible(a, b):
                    continue
                base = self._candidate((a, b), rejected)
                if base is None:
                    continue
                candidates.setdefault(base.keys, base)
                expanded = base
                for station in stations:
                    if station in {r.device_id for r in expanded.rays}:
                        continue
                    possibilities = [r for r in groups[station]
                                     if all(self._compatible(r, old) for old in expanded.rays)]
                    possibilities.sort(key=lambda r: _ray_angle_deg(r, np.asarray(expanded.localization.position)))
                    for extra in possibilities[:3]:
                        if _ray_angle_deg(extra, np.asarray(expanded.localization.position)) > float(self.options.get("association_angular_gate_deg", 1.5)):
                            continue
                        proposal = self._candidate((*expanded.rays, extra), rejected)
                        if proposal is not None:
                            expanded = proposal
                            break
                if len(candidates) < limit:
                    candidates.setdefault(expanded.keys, expanded)
            if truncated:
                break
        return sorted(candidates.values(), key=lambda c: (c.quality, c.localization.residual_m)), truncated

    def _measurement(self, track: _Filter, loc: Localization, t: float) -> tuple[np.ndarray, np.ndarray]:
        # 图像处理有延迟：把历史测量沿当前速度搬移到滤波时刻，并扩大
        # 协方差。它是短延迟一阶补偿，不是乱序量测平滑器；大延迟需拒绝。
        age = max(0., t - loc.t)
        position = np.asarray(loc.position) + track.x[3:] * age
        covariance = np.asarray(loc.covariance) + track.p[3:, 3:] * age ** 2
        accel = float(self.options.get("process_accel_std_mps2", 3.0))
        covariance = covariance + np.eye(3) * (accel * age ** 2 / 2) ** 2
        return position, covariance

    def _assignment_cost(self, track: _Filter, candidate: _Candidate, t: float) -> float:
        if track.class_id != candidate.localization.class_id:
            return 1e9
        position, covariance = self._measurement(track, candidate.localization, t)
        innovation = position - track.x[:3]
        if np.linalg.norm(innovation) > float(self.options.get("track_gate_distance_m", 30.)):
            return 1e9
        try:
            mahalanobis = float(innovation @ np.linalg.solve(track.p[:3, :3] + covariance, innovation))
        except np.linalg.LinAlgError:
            return 1e9
        if mahalanobis > float(self.options.get("track_gate_mahalanobis", 16.27)):
            return 1e9
        return mahalanobis + candidate.quality

    def _correct(self, track: _Filter, loc: Localization, t: float) -> None:
        position, covariance = self._measurement(track, loc, t)
        h = np.zeros((3, 6))
        h[:, :3] = np.eye(3)
        innovation_cov = h @ track.p @ h.T + covariance
        gain = np.linalg.solve(innovation_cov, h @ track.p).T
        track.x += gain @ (position - h @ track.x)
        # Joseph 形式数值更稳定，长期运行时避免协方差失去半正定性。
        identity = np.eye(6) - gain @ h
        track.p = identity @ track.p @ identity.T + gain @ covariance @ gain.T
        track.p = (track.p + track.p.T) / 2
        track.last_seen_t = max(track.last_seen_t, loc.t)
        track.hits += 1
        track.device_ids = loc.device_ids

    def _birth(self, loc: Localization, t: float) -> _Filter:
        track_id = f"T{self._next_id:04d}"
        self._next_id += 1
        covariance = np.zeros((6, 6))
        covariance[:3, :3] = np.asarray(loc.covariance)
        covariance[3:, 3:] = np.eye(3) * float(self.options.get("initial_velocity_std_mps", 10.)) ** 2
        track = _Filter(track_id, np.r_[loc.position, [0., 0., 0.]], covariance,
                        loc.t, loc.t, 1, loc.class_id, loc.device_ids)
        self._predict(track, t)
        self._tracks[track_id] = track
        return track

    def update(self, rays: Sequence[Ray], t: float) -> tuple[list[Track], list[Localization], dict[str, Any]]:
        """处理新射线、预测所有存活轨迹并返回本轮真正接受的定位。

        tracks 包含测量更新和暂失预测；``measured=False`` 的输出不能
        计作本轮成功定位。localizations 只包含消费至少两站新观测得到
        的定位结果。diagnostics 中歧义列表可进入 CSV 供事后审查。
        """
        if not np.isfinite(t) or self._last_t is not None and t < self._last_t:
            raise ValueError("融合器需要有限且单调不减的时间戳")
        self._last_t = t
        rejected: Counter = Counter()
        age_limit = float(self.options.get("max_measurement_age_s", .5))
        timeout = float(self.options.get("track_timeout_s", 2.0))
        diagnostics: dict[str, Any] = {"input_rays": len(rays), "duplicate_rays": 0,
                                      "ambiguities": [], "deleted_track_ids": []}
        for ray in rays:
            key = _key(ray)
            if key in self._seen:
                diagnostics["duplicate_rays"] += 1
                continue
            self._seen[key] = t
            if not np.isfinite(ray.t) or ray.t > t + 1e-6:
                rejected["future_or_invalid_timestamp"] += 1
                continue
            if t - ray.t > age_limit:
                rejected["stale_measurement"] += 1
                continue
            # 有限输入检查提前执行，避免单条非法射线污染假设排序。
            values = [*ray.origin, *ray.direction, ray.confidence, ray.angular_std_deg, ray.time_uncertainty_s]
            if not np.all(np.isfinite(values)) or not 0 < ray.confidence <= 1:
                rejected["invalid_ray"] += 1
                continue
            self._buffer[key] = ray
        self._seen = {key: value for key, value in self._seen.items() if t - value < max(5., 2 * timeout, 2 * age_limit)}
        self._buffer = {key: ray for key, ray in self._buffer.items() if 0 <= t - ray.t <= age_limit}
        active_rays = sorted(self._buffer.values(), key=lambda r: (-r.t, -r.confidence))
        max_rays = int(self.options.get("max_rays", 80))
        if len(active_rays) > max_rays:
            rejected["ray_budget"] += len(active_rays) - max_rays
            active_rays = active_rays[:max_rays]
        diagnostics["buffered_rays"] = len(active_rays)
        for track_id, track in list(self._tracks.items()):
            if t - track.last_seen_t > timeout:
                diagnostics["deleted_track_ids"].append(track_id)
                del self._tracks[track_id]
            else:
                self._predict(track, t)
        candidates, truncated = self._make_candidates(active_rays, rejected)
        diagnostics["candidate_count"] = len(candidates)
        diagnostics["hypothesis_budget_exhausted"] = truncated
        tracks = list(self._tracks.values())
        used_keys: set[tuple[str, str]] = set()
        selected: list[tuple[_Candidate, _Filter]] = []
        updated_ids: set[str] = set()
        used_candidates: set[int] = set()
        if tracks and candidates:
            costs = np.array([[self._assignment_cost(track, c, t) for track in tracks] for c in candidates])
            rows, cols = linear_sum_assignment(costs)
            proposals = sorted(zip(rows, cols), key=lambda rc: costs[rc])
            # 匈牙利解只保证候选/轨迹互斥，还需明确禁止同一检测出现在
            # 两个候选中。冲突后用剩余门控匹配补齐；这是有界近似算法。
            proposals.extend(sorted(((i, j) for i in range(len(candidates)) for j in range(len(tracks))),
                                    key=lambda rc: costs[rc]))
            for row, col in proposals:
                candidate, track = candidates[row], tracks[col]
                if costs[row, col] >= 1e8 or row in used_candidates or track.track_id in updated_ids or candidate.keys & used_keys:
                    continue
                self._correct(track, candidate.localization, t)
                selected.append((candidate, track))
                used_candidates.add(row)
                used_keys.update(candidate.keys)
                updated_ids.add(track.track_id)
        for index, candidate in enumerate(candidates):
            if index in used_candidates or candidate.keys & used_keys:
                continue
            # 已有轨迹本轮已被其他站观测更新时，不从另一个相容的独立
            # 站对再次建立同一目标。它被诊断保留，避免一物多轨。
            if any(np.linalg.norm(np.asarray(previous.localization.position) - candidate.localization.position)
                   < float(self.options.get("birth_merge_distance_m", 1.0))
                   for previous, _ in selected):
                rejected["birth_near_updated_track"] += 1
                continue
            track = self._birth(candidate.localization, t)
            selected.append((candidate, track))
            used_keys.update(candidate.keys)
            updated_ids.add(track.track_id)
        # 纯几何的多解无法保证跨相机身份正确。若共享观测存在质量接近
        # 但空间分离的替代交点，保留明确诊断供算法评估和离线人工检查。
        margin = float(self.options.get("ambiguity_margin", .15))
        distance_gate = float(self.options.get("ambiguity_distance_m", 2.))
        for candidate, track in selected:
            alternatives = [other for other in candidates
                            if other.keys != candidate.keys and other.keys & candidate.keys
                            and abs(other.quality - candidate.quality) <= margin
                            and np.linalg.norm(np.asarray(other.localization.position) - candidate.localization.position) > distance_gate]
            if alternatives:
                diagnostics["ambiguities"].append({"track_id": track.track_id,
                    "selected_detection_ids": list(candidate.localization.detection_ids),
                    "alternative_count": len(alternatives),
                    "message": "共享检测存在相近质量的不同空间假设，身份可能不可靠"})
        for key in used_keys:
            self._buffer.pop(key, None)
        confirmation = int(self.options.get("confirmation_hits", 3))
        estimates = []
        for track in self._tracks.values():
            measured = track.track_id in updated_ids
            status = ("confirmed" if track.hits >= confirmation else "tentative") if measured else "coasting"
            estimates.append(Track(track.track_id, t, tuple(float(v) for v in track.x[:3]),
                tuple(float(v) for v in track.x[3:]), tuple(tuple(float(v) for v in row) for row in track.p),
                track.last_seen_t, track.hits, status, track.device_ids if measured else (), track.class_id, measured))
        diagnostics["rejections"] = dict(rejected)
        diagnostics["localized_count"] = len(selected)
        diagnostics["track_count"] = len(estimates)
        diagnostics["ambiguous_count"] = len(diagnostics["ambiguities"])
        return estimates, [c.localization for c, _ in selected], diagnostics
