from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import math
import time
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix
from scipy.stats import norm

from ..geometry import intrinsics_at_zoom, project_world_points, world_to_gimbal_angles
from ..models import Action, PolicyContext, Telemetry
from .types import SolverDiagnostics


def angle_delta_deg(a: float, b: float) -> float:
    """Shortest signed angular difference a-b in degrees."""
    return (float(a) - float(b) + 180.0) % 360.0 - 180.0


def _zoom_levels(device, configured) -> list[float]:
    lo, hi = map(float, device.zoom_limits)
    levels = configured or [lo, (lo + hi) / 2.0, hi]
    return sorted({float(np.clip(float(z), lo, hi)) for z in levels})


def _half_fov_deg(device, zoom: float) -> tuple[float, float]:
    k = intrinsics_at_zoom(device, zoom)
    hx_px = max(1e-9, min(k.cx, k.width - k.cx))
    hy_px = max(1e-9, min(k.cy, k.height - k.cy))
    return math.degrees(math.atan(hx_px / k.fx)), math.degrees(math.atan(hy_px / k.fy))


@dataclass(frozen=True)
class PredictedTrack:
    track_id: str
    positions: np.ndarray
    covariances: np.ndarray
    speeds: np.ndarray
    current_devices: tuple[str, ...]


@dataclass(frozen=True)
class Primitive:
    index: int
    device_id: str
    kind: str
    yaw_deg: float
    pitch_deg: float
    zoom: float
    target_ids: tuple[str, ...]
    transition_s: float
    ready_slot: int
    visibility: np.ndarray
    search_coverage: np.ndarray
    execution_cost: float

    def action(self, t: float, ttl_s: float) -> Action:
        return Action(self.device_id, yaw_deg=self.yaw_deg, pitch_deg=self.pitch_deg,
                      zoom=self.zoom, target_ids=self.target_ids,
                      reason=f"research_{self.kind}", issued_t=t, ttl_s=ttl_s)


@dataclass(frozen=True)
class PrimitiveSet:
    by_device: dict[str, tuple[Primitive, ...]]
    flat: tuple[Primitive, ...]
    target_ids: tuple[str, ...]
    search_positions: np.ndarray
    search_ages_s: np.ndarray
    horizon_steps: int
    slot_s: float
    overlap_requirements: tuple[tuple[int, int, float], ...]


class PrimitiveFactory:
    """Generate a common physically executable candidate set for all baselines."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.devices = {d.id: d for d in cfg.active_devices}
        research = cfg.policy.get("research", {})
        planning = research.get("planning", {})
        execution = research.get("execution", {})
        self.horizon_s = float(planning.get("horizon_s", 3.0))
        self.slot_s = float(planning.get("slot_s", 0.5))
        self.horizon_steps = max(1, int(math.ceil(self.horizon_s / self.slot_s)))
        self.max_search_candidates = int(planning.get("search_candidates_per_device", 8))
        self.max_shared_targets = int(planning.get("max_shared_targets", 2))
        self.process_noise_m2ps = float(planning.get("prediction_process_noise_m2ps", 0.5))
        self.risk_budget = float(planning.get("visibility_risk", 0.05))
        self.use_uncertainty = bool(planning.get("use_uncertainty", True))
        self.inter_sample_factor = float(planning.get("inter_sample_motion_factor", 0.5))
        self.fov_margin_deg = float(planning.get("fov_margin_deg", 0.25))
        self.handover_overlap_s = float(planning.get("handover_overlap_s", 0.5))
        self.zoom_rate = float(execution.get("zoom_rate_per_s", cfg.simulation.get("zoom_rate_per_s", 3.0)))
        self.settle_s = float(execution.get("settle_s", 0.25))
        self.search_zooms = planning.get("search_zoom_levels", [1.0, 3.0])
        self.track_zooms = planning.get("tracking_zoom_levels", [3.0, 5.0, 8.0, 10.0])
        self.ttl_s = float(planning.get("action_ttl_s", max(0.5, 2 / float(cfg.system.get("rate_hz", 10)))))
        if self.horizon_s <= 0 or self.slot_s <= 0 or self.max_search_candidates < 0 or self.max_shared_targets < 1:
            raise ValueError("invalid research planning horizon/candidate settings")
        if not 0 < self.risk_budget < 1:
            raise ValueError("visibility_risk must lie in (0,1)")
        if self.zoom_rate <= 0 or self.settle_s < 0:
            raise ValueError("invalid research execution model")

    def predict_tracks(self, context: PolicyContext) -> tuple[PredictedTrack, ...]:
        result = []
        for track in sorted(context.tracks, key=lambda x: x.track_id):
            p0 = np.asarray(track.position, dtype=float)
            v = np.asarray(track.velocity, dtype=float)
            covariance = np.asarray(track.covariance, dtype=float)
            if p0.shape != (3,) or v.shape != (3,) or covariance.shape != (3, 3):
                continue
            positions, covariances, speeds = [], [], []
            for h in range(self.horizon_steps):
                tau = (h + 1) * self.slot_s
                positions.append(p0 + v * tau)
                covariances.append(covariance + np.eye(3) * self.process_noise_m2ps * tau)
                speeds.append(float(np.linalg.norm(v)))
            result.append(PredictedTrack(track.track_id, np.asarray(positions), np.asarray(covariances),
                                         np.asarray(speeds), tuple(track.device_ids)))
        return tuple(result)

    def _transition_s(self, state, device, yaw: float, pitch: float, zoom: float) -> float:
        yaw_t = abs(angle_delta_deg(yaw, state.yaw_deg)) / float(device.max_slew_dps)
        pitch_t = abs(float(pitch) - float(state.pitch_deg)) / float(device.max_slew_dps)
        zoom_t = abs(float(zoom) - float(state.zoom)) / self.zoom_rate
        return max(yaw_t, pitch_t, zoom_t) + self.settle_s

    def _within_limits(self, device, yaw, pitch, zoom) -> bool:
        return (device.yaw_limits_deg[0] - 1e-9 <= yaw <= device.yaw_limits_deg[1] + 1e-9 and
                device.pitch_limits_deg[0] - 1e-9 <= pitch <= device.pitch_limits_deg[1] + 1e-9 and
                device.zoom_limits[0] - 1e-9 <= zoom <= device.zoom_limits[1] + 1e-9)

    def _risk_multiplier(self, n_targets: int) -> float:
        if not self.use_uncertainty:
            return 0.0
        checks = max(1, n_targets * self.horizon_steps * 2)
        per_side = max(min(self.risk_budget / checks / 2.0, 0.49), 1e-9)
        return float(min(norm.ppf(1.0 - per_side), 6.0))

    def _visibility(self, device, yaw, pitch, zoom, ready_slot, predicted: tuple[PredictedTrack, ...]) -> np.ndarray:
        matrix = np.zeros((len(predicted), self.horizon_steps), dtype=bool)
        try:
            half_yaw, half_pitch = _half_fov_deg(device, zoom)
        except ValueError:
            return matrix
        kappa = self._risk_multiplier(max(len(predicted), 1))
        origin = np.asarray(device.position_m, dtype=float)
        for j, track in enumerate(predicted):
            for h in range(max(0, ready_slot), self.horizon_steps):
                point = track.positions[h]
                try:
                    target_yaw, target_pitch = world_to_gimbal_angles(point, device)
                except ValueError:
                    continue
                distance = max(float(np.linalg.norm(point - origin)), 1e-3)
                covariance = track.covariances[h]
                sigma_pos = math.sqrt(max(float(np.linalg.eigvalsh(covariance).max()), 0.0)) if self.use_uncertainty else 0.0
                sigma_angle = math.degrees(math.atan2(sigma_pos, distance))
                angular_speed = math.degrees(math.atan2(float(track.speeds[h]), distance))
                inter = angular_speed * self.slot_s * self.inter_sample_factor
                margin = kappa * sigma_angle + inter + self.fov_margin_deg
                if (abs(angle_delta_deg(target_yaw, yaw)) + margin <= half_yaw and
                        abs(target_pitch - pitch) + margin <= half_pitch):
                    matrix[j, h] = True
        return matrix

    def _search_coverage(self, device, yaw, pitch, zoom, ready_slot, search_positions) -> np.ndarray:
        matrix = np.zeros((len(search_positions), self.horizon_steps), dtype=bool)
        if ready_slot >= self.horizon_steps or not len(search_positions):
            return matrix
        state = Telemetry(device.id, 0.0, float(yaw), float(pitch), zoom=float(zoom), source="planning")
        try:
            projected = project_world_points(search_positions, state, device)
        except ValueError:
            return matrix
        visible = np.fromiter((p is not None for p in projected), dtype=bool, count=len(search_positions))
        matrix[:, max(0, ready_slot):] = visible[:, None]
        return matrix

    def _make(self, index, device, state, kind, yaw, pitch, zoom, target_ids,
              predicted, search_positions, ready_override: int | None = None) -> Primitive | None:
        yaw, pitch, zoom = float(yaw), float(pitch), float(zoom)
        if not self._within_limits(device, yaw, pitch, zoom):
            return None
        transition = self._transition_s(state, device, yaw, pitch, zoom)
        ready = int(math.ceil(max(0.0, transition - 1e-12) / self.slot_s))
        if ready_override is not None:
            ready = max(0, int(ready_override))
            transition = ready * self.slot_s
        visibility = self._visibility(device, yaw, pitch, zoom, ready, predicted)
        search = self._search_coverage(device, yaw, pitch, zoom, ready, search_positions)
        cost = transition + 0.02 * abs(zoom - float(state.zoom))
        return Primitive(index, device.id, kind, yaw, pitch, zoom, tuple(target_ids), transition,
                         ready, visibility, search, cost)

    def _hold_ready_slot(self, context: PolicyContext, device_id: str) -> int:
        readiness = context.research.get("readiness", {}).get(device_id, {})
        if readiness.get("sensing_valid") is True:
            return 0
        reason = readiness.get("reason")
        stable_since = readiness.get("stable_since")
        if reason == "settling" and stable_since is not None:
            remaining = max(0.0, self.settle_s - (context.t - float(stable_since)))
        else:
            # A hold command first arrests the virtual movement; the sensor then
            # needs a complete settling interval before it can be counted.
            remaining = self.settle_s
        return int(math.ceil(max(0.0, remaining - 1e-12) / self.slot_s))

    def generate(self, context: PolicyContext) -> PrimitiveSet:
        search = context.research.get("search", {})
        search_positions = np.asarray(search.get("positions_m", []), dtype=float)
        search_ages = np.asarray(search.get("ages_s", []), dtype=float)
        if search_positions.size == 0:
            search_positions = np.empty((0, 3), dtype=float)
            search_ages = np.empty((0,), dtype=float)
        if search_positions.ndim != 2 or (len(search_positions) and search_positions.shape[1] != 3):
            raise ValueError("research search positions must be N x 3")
        if search_ages.shape != (len(search_positions),):
            raise ValueError("research search ages do not match positions")
        predicted = self.predict_tracks(context)
        target_ids = tuple(x.track_id for x in predicted)
        by_device: dict[str, list[Primitive]] = {key: [] for key in self.devices}
        serial = 0
        stale_order = np.argsort(-search_ages, kind="stable")[:max(self.max_search_candidates * 2, self.max_search_candidates)]
        for key, device in self.devices.items():
            state = context.devices.get(key)
            if state is None or not state.connected:
                continue
            candidates: list[tuple[str, float, float, float, tuple[str, ...]]] = []
            candidates.append(("hold", state.yaw_deg, state.pitch_deg, state.zoom, tuple()))
            for cell in stale_order:
                try:
                    yaw, pitch = world_to_gimbal_angles(search_positions[int(cell)], device)
                except ValueError:
                    continue
                for zoom in _zoom_levels(device, self.search_zooms):
                    candidates.append(("search", yaw, pitch, zoom, tuple()))
                    break
                if sum(1 for row in candidates if row[0] == "search") >= self.max_search_candidates:
                    break
            for track in predicted:
                mid = min(self.horizon_steps - 1, max(0, self.horizon_steps // 2))
                try:
                    yaw, pitch = world_to_gimbal_angles(track.positions[mid], device)
                except ValueError:
                    continue
                for zoom in _zoom_levels(device, self.track_zooms):
                    candidates.append(("track", yaw, pitch, zoom, (track.track_id,)))
            for size in range(2, min(self.max_shared_targets, len(predicted)) + 1):
                for group in combinations(predicted, size):
                    mid = min(self.horizon_steps - 1, max(0, self.horizon_steps // 2))
                    point = np.mean([item.positions[mid] for item in group], axis=0)
                    try:
                        yaw, pitch = world_to_gimbal_angles(point, device)
                    except ValueError:
                        continue
                    ids = tuple(item.track_id for item in group)
                    for zoom in _zoom_levels(device, self.track_zooms):
                        candidates.append(("shared_track", yaw, pitch, zoom, ids))
            seen = set()
            for kind, yaw, pitch, zoom, ids in candidates:
                signature = (round(float(yaw), 5), round(float(pitch), 5), round(float(zoom), 5))
                if signature in seen:
                    continue
                seen.add(signature)
                ready_override = self._hold_ready_slot(context, key) if kind == "hold" else None
                primitive = self._make(serial, device, state, kind, yaw, pitch, zoom, ids,
                                       predicted, search_positions, ready_override=ready_override)
                if primitive is not None:
                    by_device[key].append(primitive)
                    serial += 1
        flat = tuple(item for key in self.devices for item in by_device[key])
        overlap: list[tuple[int, int, float]] = []
        if self.handover_overlap_s > 0:
            overlap_slots = max(1, int(math.ceil(self.handover_overlap_s / self.slot_s)))
            for j, track in enumerate(predicted):
                sources = tuple(x for x in track.current_devices if x in by_device)
                if len(sources) != 1:
                    continue
                source = sources[0]
                hold = next((p for p in by_device[source] if p.kind == "hold"), None)
                if hold is None:
                    continue
                false_slots = np.flatnonzero(~hold.visibility[j])
                if not len(false_slots):
                    continue
                first_loss = int(false_slots[0])
                start = max(0, first_loss - overlap_slots)
                for h in range(start, first_loss):
                    alternative = any(p.device_id != source and p.visibility[j, h] for p in flat)
                    if alternative and hold.visibility[j, h]:
                        overlap.append((j, h, 2.0))
        return PrimitiveSet({k: tuple(v) for k, v in by_device.items()}, flat, target_ids,
                            search_positions, search_ages, self.horizon_steps, self.slot_s,
                            tuple(overlap))


@dataclass
class _MILPLayout:
    nx: int
    ns: int
    ny: int
    x0: int
    s0: int
    y0: int
    nvar: int


class HorizonMILP:
    """Shared MILP builder used by ECP-RH and the weighted-MPC baseline."""

    def __init__(self, primitive_set: PrimitiveSet, time_limit_s: float = 0.2,
                 mip_rel_gap: float = 1e-4):
        self.ps = primitive_set
        self.time_limit_s = max(float(time_limit_s), 1e-3)
        self.mip_rel_gap = max(float(mip_rel_gap), 0.0)
        self.C = len(primitive_set.flat)
        self.J = len(primitive_set.target_ids)
        self.H = primitive_set.horizon_steps
        self.G = len(primitive_set.search_positions)
        self.layout = _MILPLayout(self.C, self.J * self.H, self.G * self.H,
                                  0, self.C, self.C + self.J * self.H,
                                  self.C + self.J * self.H + self.G * self.H)
        self._candidate_index = {p.index: i for i, p in enumerate(primitive_set.flat)}
        self._base_A, self._base_lb, self._base_ub = self._base_constraints()
        self.bounds = Bounds(np.zeros(self.layout.nvar), np.ones(self.layout.nvar))
        self.integrality = np.zeros(self.layout.nvar, dtype=int)
        self.integrality[:self.C] = 1

    def _base_constraints(self):
        rows: list[int] = []
        cols: list[int] = []
        data: list[float] = []
        lb: list[float] = []
        ub: list[float] = []
        row = 0
        for _, candidates in self.ps.by_device.items():
            if not candidates:
                continue
            for p in candidates:
                rows.append(row); cols.append(self._candidate_index[p.index]); data.append(1.0)
            lb.append(1.0); ub.append(1.0); row += 1
        for j in range(self.J):
            for h in range(self.H):
                for p in self.ps.flat:
                    if p.visibility[j, h]:
                        rows.append(row); cols.append(self._candidate_index[p.index]); data.append(1.0)
                s = self.layout.s0 + j * self.H + h
                rows.append(row); cols.append(s); data.append(1.0)
                lb.append(1.0); ub.append(np.inf); row += 1
        for g in range(self.G):
            for h in range(self.H):
                for p in self.ps.flat:
                    if p.search_coverage[g, h]:
                        rows.append(row); cols.append(self._candidate_index[p.index]); data.append(1.0)
                y = self.layout.y0 + g * self.H + h
                rows.append(row); cols.append(y); data.append(-1.0)
                lb.append(0.0); ub.append(np.inf); row += 1
        for j, h, required in self.ps.overlap_requirements:
            for p in self.ps.flat:
                if p.visibility[j, h]:
                    rows.append(row); cols.append(self._candidate_index[p.index]); data.append(1.0)
            lb.append(float(required)); ub.append(np.inf); row += 1
        A = coo_matrix((data, (rows, cols)), shape=(row, self.layout.nvar)).tocsr()
        return A, np.asarray(lb, dtype=float), np.asarray(ub, dtype=float)

    def _search_weights(self) -> np.ndarray:
        if not self.G:
            return np.empty(0, dtype=float)
        weights = np.zeros(self.G * self.H, dtype=float)
        for g, age in enumerate(self.ps.search_ages_s):
            for h in range(self.H):
                weights[g * self.H + h] = max(0.0, float(age) + (h + 1) * self.ps.slot_s)
        scale = max(float(weights.max()), 1.0)
        return weights / scale

    def _constraints_with(self, extra_rows: list[tuple[np.ndarray, float, float]] | None = None):
        if not extra_rows:
            return LinearConstraint(self._base_A, self._base_lb, self._base_ub)
        from scipy.sparse import vstack, csr_matrix
        mats = [self._base_A]; lbs = [self._base_lb]; ubs = [self._base_ub]
        for vector, lower, upper in extra_rows:
            mats.append(csr_matrix(vector.reshape(1, -1)))
            lbs.append(np.asarray([lower], dtype=float)); ubs.append(np.asarray([upper], dtype=float))
        return LinearConstraint(vstack(mats).tocsr(), np.concatenate(lbs), np.concatenate(ubs))

    def _solve(self, objective: np.ndarray, extra=None):
        return milp(objective, integrality=self.integrality, bounds=self.bounds,
                    constraints=self._constraints_with(extra),
                    options={"time_limit": self.time_limit_s, "mip_rel_gap": self.mip_rel_gap, "presolve": True})

    @staticmethod
    def _status(result) -> tuple[str, bool]:
        table = {0: "optimal", 1: "limit", 2: "infeasible", 3: "unbounded", 4: "error"}
        code = int(getattr(result, "status", 4))
        return table.get(code, "error"), code == 1

    def selected(self, x: np.ndarray | None) -> tuple[Primitive, ...]:
        if x is None:
            return ()
        return tuple(p for i, p in enumerate(self.ps.flat) if x[i] >= 0.5)

    def solve_lexicographic(self, method="ecprh") -> tuple[tuple[Primitive, ...], SolverDiagnostics]:
        start = time.perf_counter()
        diag = SolverDiagnostics(method=method, candidate_count=self.C)
        c1 = np.zeros(self.layout.nvar)
        c1[self.layout.s0:self.layout.s0 + self.layout.ns] = self.ps.slot_s
        r1 = self._solve(c1)
        status1, limit1 = self._status(r1)
        if r1.x is None:
            diag.status, diag.timeout, diag.solve_ms = status1, limit1, (time.perf_counter() - start) * 1000
            return (), diag
        j1 = float(c1 @ r1.x)
        diag.level1 = j1
        weights = self._search_weights()
        c2 = np.zeros(self.layout.nvar)
        if len(weights):
            c2[self.layout.y0:self.layout.y0 + self.layout.ny] = -weights
        lock1 = (c1.copy(), -np.inf, j1 + 1e-7)
        r2 = self._solve(c2, [lock1])
        if r2.x is None:
            diag.status, diag.timeout = status1, limit1
            diag.solve_ms = (time.perf_counter() - start) * 1000
            diag.mip_gap = getattr(r1, "mip_gap", None)
            return self.selected(r1.x), diag
        j2 = float(-c2 @ r2.x)
        diag.level2 = j2
        c3 = np.zeros(self.layout.nvar)
        for i, p in enumerate(self.ps.flat):
            c3[i] = p.execution_cost
        lock2 = ((-c2).copy(), j2 - 1e-7, np.inf)
        r3 = self._solve(c3, [lock1, lock2])
        result = r3 if r3.x is not None else r2
        diag.level3 = float(c3 @ result.x) if result.x is not None else None
        statuses = [self._status(r)[0] for r in (r1, r2, r3)]
        diag.status = "/".join(statuses)
        diag.timeout = any(self._status(r)[1] for r in (r1, r2, r3))
        diag.mip_gap = getattr(result, "mip_gap", None)
        diag.solve_ms = (time.perf_counter() - start) * 1000
        diag.extras = {"overlap_constraints": len(self.ps.overlap_requirements),
                       "horizon_steps": self.H, "slot_s": self.ps.slot_s}
        return self.selected(result.x), diag

    def solve_weighted(self, loss_weight=10.0, search_weight=1.0, motion_weight=0.1,
                       method="weighted_rh") -> tuple[tuple[Primitive, ...], SolverDiagnostics]:
        start = time.perf_counter()
        c = np.zeros(self.layout.nvar)
        if self.layout.ns:
            c[self.layout.s0:self.layout.s0 + self.layout.ns] = float(loss_weight) / max(self.layout.ns, 1)
        weights = self._search_weights()
        if len(weights):
            c[self.layout.y0:self.layout.y0 + self.layout.ny] = -float(search_weight) * weights / max(len(weights), 1)
        horizon = max(self.horizon_s_equivalent(), 1e-9)
        for i, p in enumerate(self.ps.flat):
            c[i] += float(motion_weight) * p.execution_cost / horizon
        result = self._solve(c)
        status, limit = self._status(result)
        diag = SolverDiagnostics(method=method, status=status, timeout=limit,
                                 solve_ms=(time.perf_counter() - start) * 1000,
                                 mip_gap=getattr(result, "mip_gap", None), candidate_count=self.C)
        if result.x is not None:
            s = result.x[self.layout.s0:self.layout.s0 + self.layout.ns]
            diag.level1 = float(np.sum(s) * self.ps.slot_s)
            if len(weights):
                y = result.x[self.layout.y0:self.layout.y0 + self.layout.ny]
                diag.level2 = float(weights @ y)
            diag.level3 = float(sum(p.execution_cost * result.x[i] for i, p in enumerate(self.ps.flat)))
        return self.selected(result.x), diag

    def horizon_s_equivalent(self) -> float:
        return self.ps.horizon_steps * self.ps.slot_s
