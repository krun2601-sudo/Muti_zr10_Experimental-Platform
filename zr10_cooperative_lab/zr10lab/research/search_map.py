from __future__ import annotations

from itertools import product
import math
from typing import Any

import numpy as np

from ..geometry import project_world_points
from .types import DeviceReadiness, SearchGridSnapshot


class ReadinessTracker:
    """Track whether each virtual PTZ can currently contribute a valid observation.

    Movement/zoom transition resets the settling timer.  This belongs to the
    experiment world rather than any policy so every baseline sees the same
    sensor availability.
    """

    def __init__(self, cfg):
        research = cfg.policy.get("research", {})
        execution = research.get("execution", {})
        self.settle_s = float(execution.get("settle_s", 0.25))
        self.rate_tol_dps = float(execution.get("settle_rate_tolerance_dps", 0.15))
        self.zoom_tol = float(execution.get("zoom_stable_tolerance", 1e-3))
        self.allow_moving = bool(execution.get("allow_sensing_while_moving", False))
        if self.settle_s < 0 or self.rate_tol_dps < 0 or self.zoom_tol < 0:
            raise ValueError("research execution settling parameters must be non-negative")
        self._last_zoom: dict[str, float] = {}
        self._stable_since: dict[str, float | None] = {}
        self._last_t: float | None = None

    def reset(self) -> None:
        self._last_zoom.clear()
        self._stable_since.clear()
        self._last_t = None

    def update(self, t: float, states: dict) -> dict[str, DeviceReadiness]:
        if self._last_t is not None and t < self._last_t - 1e-9:
            raise ValueError("research time moved backwards")
        result: dict[str, DeviceReadiness] = {}
        for key, state in states.items():
            previous_zoom = self._last_zoom.get(key, float(state.zoom))
            zoom_moving = abs(float(state.zoom) - previous_zoom) > self.zoom_tol
            angular_moving = max(abs(float(state.yaw_rate_dps)), abs(float(state.pitch_rate_dps))) > self.rate_tol_dps
            connected = bool(state.connected)
            moving = angular_moving or zoom_moving
            if not connected:
                self._stable_since[key] = None
                valid, reason = False, "disconnected"
            elif self.allow_moving:
                if self._stable_since.get(key) is None:
                    self._stable_since[key] = t
                valid, reason = True, "moving_allowed"
            elif moving:
                self._stable_since[key] = None
                valid, reason = False, "moving_or_zooming"
            else:
                stable_since = self._stable_since.get(key)
                if stable_since is None:
                    stable_since = t
                    self._stable_since[key] = t
                valid = t - stable_since + 1e-12 >= self.settle_s
                reason = "ready" if valid else "settling"
            self._last_zoom[key] = float(state.zoom)
            result[key] = DeviceReadiness(key, valid, self._stable_since.get(key), reason)
        self._last_t = float(t)
        return result


class PersistentSearchMap:
    """Discretized persistent-search freshness state shared by every method."""

    def __init__(self, cfg):
        research = cfg.policy.get("research", {})
        options = research.get("search", {})
        roi = options.get("roi", research.get("scenario", {}).get("roi", cfg.policy.get("roi")))
        if not roi:
            raise ValueError("research persistent search needs an ROI")
        shape = options.get("grid", [7, 7, 3])
        if len(shape) != 3 or any(int(n) != n or int(n) <= 0 for n in shape):
            raise ValueError("research.search.grid must contain three positive integers")
        self.shape = tuple(int(n) for n in shape)
        axes = [np.linspace(float(roi[k][0]), float(roi[k][1]), self.shape[i])
                for i, k in enumerate(("x", "y", "z"))]
        self.positions = np.asarray(list(product(*axes)), dtype=float)
        self.initial_age_s = float(options.get("initial_age_s", 0.0))
        self.age_cap_s = float(options.get("age_cap_s", 1e6))
        if self.initial_age_s < 0 or self.age_cap_s <= 0:
            raise ValueError("search ages must be non-negative and age_cap_s positive")
        self.reset(0.0)

    def reset(self, t0: float = 0.0) -> None:
        # last_visit=t0-initial_age gives an immediately interpretable age.
        self.last_visit = np.full(len(self.positions), float(t0) - self.initial_age_s, dtype=float)
        self.ever_observed = np.zeros(len(self.positions), dtype=bool)
        self._last_t = float(t0)
        self._observed_now = np.zeros(len(self.positions), dtype=bool)

    def update(self, t: float, states: dict, readiness: dict, device_configs: dict) -> SearchGridSnapshot:
        if t < self._last_t - 1e-9:
            raise ValueError("search-map time moved backwards")
        observed = np.zeros(len(self.positions), dtype=bool)
        for key, state in states.items():
            ready = readiness.get(key)
            if ready is None or not ready.sensing_valid:
                continue
            config = device_configs.get(key)
            if config is None:
                continue
            try:
                projected = project_world_points(self.positions, state, config)
            except ValueError:
                continue
            observed |= np.fromiter((p is not None for p in projected), dtype=bool, count=len(projected))
        self.last_visit[observed] = float(t)
        self.ever_observed |= observed
        self._observed_now = observed
        self._last_t = float(t)
        return self.snapshot(t)

    def snapshot(self, t: float) -> SearchGridSnapshot:
        ages = np.clip(float(t) - self.last_visit, 0.0, self.age_cap_s)
        return SearchGridSnapshot(self.positions.copy(), ages, self.last_visit.copy(), self._observed_now.copy())

    def metrics(self, t: float) -> dict[str, float]:
        snap = self.snapshot(t)
        ages = snap.ages_s
        return {
            "research_search_coverage_fraction": float(np.mean(self.ever_observed)),
            "research_revisit_age_mean_s": float(np.mean(ages)),
            "research_revisit_age_p95_s": float(np.percentile(ages, 95)),
            "research_revisit_age_max_s": float(np.max(ages)),
            "research_instant_search_fraction": float(np.mean(snap.observed_now)),
        }
