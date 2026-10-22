from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from .types import TruthTarget


def _vec3(value, name: str) -> np.ndarray:
    a = np.asarray(value, dtype=float)
    if a.shape != (3,) or not np.all(np.isfinite(a)):
        raise ValueError(f"{name} must contain three finite numbers")
    return a


def _roi_contains(point: np.ndarray, roi: dict[str, Any] | None) -> bool:
    if not roi:
        return True
    return all(float(roi[k][0]) <= float(point[i]) <= float(roi[k][1])
               for i, k in enumerate(("x", "y", "z")))


@dataclass(frozen=True)
class _MotionState:
    position: np.ndarray
    velocity: np.ndarray


class VirtualTargetField:
    """Deterministic target field used as private experiment truth.

    Supported trajectory models are intentionally simple and auditable.  The
    scheduler never receives the target specification or truth IDs.
    """

    def __init__(self, cfg):
        research = cfg.policy.get("research", {})
        scenario = research.get("scenario", {})
        self.roi = scenario.get("roi", cfg.policy.get("roi"))
        self.targets = list(scenario.get("targets", cfg.simulation.get("targets", [])))
        self.remove_outside_roi = bool(scenario.get("remove_outside_roi", True))
        self._validate()

    def _validate(self) -> None:
        ids: set[str] = set()
        for index, row in enumerate(self.targets):
            if not isinstance(row, dict):
                raise ValueError("research targets must be mappings")
            key = str(row.get("id", f"target_{index + 1}"))
            if not key or key in ids:
                raise ValueError(f"duplicate/empty research target id: {key!r}")
            ids.add(key)
            start = float(row.get("start_s", 0.0))
            end = float(row.get("end_s", math.inf))
            if not math.isfinite(start) or end <= start:
                raise ValueError(f"{key}: invalid start_s/end_s")
            model = str(row.get("trajectory", row.get("model", "cv"))).lower()
            if model not in {"cv", "sin", "waypoint", "turn"}:
                raise ValueError(f"{key}: unsupported trajectory {model!r}")
            if model in {"cv", "sin", "turn"}:
                _vec3(row.get("position_m", [100, 0, 60]), "position_m")
            if model in {"cv", "sin"}:
                _vec3(row.get("velocity_mps", [0, 0, 0]), "velocity_mps")
            if model == "sin":
                _vec3(row.get("amplitude_m", [0, 0, 0]), "amplitude_m")
                period = float(row.get("period_s", 30.0))
                if not math.isfinite(period) or period <= 0:
                    raise ValueError(f"{key}: period_s must be positive")
            if model == "waypoint":
                points = row.get("waypoints", [])
                if len(points) < 2:
                    raise ValueError(f"{key}: waypoint trajectory needs >=2 waypoints")
                last_t = -math.inf
                for item in points:
                    if not isinstance(item, dict) or "t_s" not in item or "position_m" not in item:
                        raise ValueError(f"{key}: every waypoint needs t_s and position_m")
                    tt = float(item["t_s"])
                    _vec3(item["position_m"], "waypoint.position_m")
                    if not math.isfinite(tt) or tt <= last_t:
                        raise ValueError(f"{key}: waypoint times must strictly increase")
                    last_t = tt
            if model == "turn":
                speed = float(row.get("speed_mps", 8.0))
                rate = float(row.get("turn_rate_dps", 5.0))
                heading = float(row.get("heading_deg", 0.0))
                climb = float(row.get("climb_mps", 0.0))
                if not all(math.isfinite(x) for x in (speed, rate, heading, climb)) or speed < 0:
                    raise ValueError(f"{key}: invalid coordinated-turn parameters")

    @staticmethod
    def _cv(row: dict[str, Any], local_t: float) -> _MotionState:
        p0 = _vec3(row.get("position_m", [100, 0, 60]), "position_m")
        v = _vec3(row.get("velocity_mps", [0, 0, 0]), "velocity_mps")
        return _MotionState(p0 + v * local_t, v)

    @staticmethod
    def _sin(row: dict[str, Any], local_t: float) -> _MotionState:
        base = VirtualTargetField._cv(row, local_t)
        amp = _vec3(row.get("amplitude_m", [0, 0, 0]), "amplitude_m")
        period = float(row.get("period_s", 30.0))
        phase = np.asarray(row.get("phase_rad", [0, 0, 0]), dtype=float)
        if phase.ndim == 0:
            phase = np.repeat(phase, 3)
        if phase.shape != (3,) or not np.all(np.isfinite(phase)):
            raise ValueError("phase_rad must be finite scalar or three-vector")
        w = 2 * np.pi / period
        position = base.position + amp * np.sin(w * local_t + phase)
        velocity = base.velocity + amp * w * np.cos(w * local_t + phase)
        return _MotionState(position, velocity)

    @staticmethod
    def _waypoint(row: dict[str, Any], absolute_t: float) -> _MotionState:
        points = row["waypoints"]
        times = np.asarray([float(p["t_s"]) for p in points], dtype=float)
        positions = np.asarray([p["position_m"] for p in points], dtype=float)
        if absolute_t <= times[0]:
            i = 0
        elif absolute_t >= times[-1]:
            i = len(times) - 2
        else:
            i = int(np.searchsorted(times, absolute_t, side="right") - 1)
        dt = max(times[i + 1] - times[i], 1e-9)
        velocity = (positions[i + 1] - positions[i]) / dt
        alpha = float(np.clip((absolute_t - times[i]) / dt, 0.0, 1.0))
        return _MotionState((1 - alpha) * positions[i] + alpha * positions[i + 1], velocity)

    @staticmethod
    def _turn(row: dict[str, Any], local_t: float) -> _MotionState:
        p0 = _vec3(row.get("position_m", [100, 0, 60]), "position_m")
        speed = float(row.get("speed_mps", 8.0))
        omega = math.radians(float(row.get("turn_rate_dps", 5.0)))
        heading0 = math.radians(float(row.get("heading_deg", 0.0)))
        climb = float(row.get("climb_mps", 0.0))
        if abs(omega) < 1e-10:
            velocity = np.array([speed * math.cos(heading0), speed * math.sin(heading0), climb])
            return _MotionState(p0 + velocity * local_t, velocity)
        heading = heading0 + omega * local_t
        x = p0[0] + speed / omega * (math.sin(heading) - math.sin(heading0))
        y = p0[1] - speed / omega * (math.cos(heading) - math.cos(heading0))
        z = p0[2] + climb * local_t
        velocity = np.array([speed * math.cos(heading), speed * math.sin(heading), climb])
        return _MotionState(np.array([x, y, z]), velocity)

    def truth(self, t: float) -> dict[str, TruthTarget]:
        result: dict[str, TruthTarget] = {}
        for index, row in enumerate(self.targets):
            start = float(row.get("start_s", 0.0))
            end = float(row.get("end_s", math.inf))
            if t < start or t > end:
                continue
            model = str(row.get("trajectory", row.get("model", "cv"))).lower()
            local_t = t - start
            if model == "cv":
                state = self._cv(row, local_t)
            elif model == "sin":
                state = self._sin(row, local_t)
            elif model == "waypoint":
                state = self._waypoint(row, t)
            elif model == "turn":
                state = self._turn(row, local_t)
            else:  # validation guards this; keep explicit for corrupted runtime config
                raise ValueError(f"unsupported trajectory: {model}")
            if self.remove_outside_roi and not _roi_contains(state.position, self.roi):
                continue
            key = str(row.get("id", f"target_{index + 1}"))
            result[key] = TruthTarget(key, float(t), tuple(float(x) for x in state.position),
                                      tuple(float(x) for x in state.velocity), True)
        return result

    def truth_positions(self, t: float) -> dict[str, tuple[float, float, float]]:
        return {key: target.position for key, target in self.truth(t).items()}
