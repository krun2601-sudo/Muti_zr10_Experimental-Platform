from __future__ import annotations

from itertools import product
import math
from typing import Any

import numpy as np

from ..geometry import project_world_points
from .sensing_quality import SensingQualityModel
from .types import DeviceReadiness, SearchGridSnapshot


class ReadinessTracker:
    """Track whether each virtual PTZ can currently contribute a valid observation.

    Movement/zoom transition resets the settling timer. This belongs to the
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
    """Persistent-search freshness state shared by every paper method.

    Two public task-domain representations are supported:

    ``cartesian`` (legacy)
        A 3-D box sampled on x/y/z.

    ``angular_shell`` (recommended for fixed EO search)
        Azimuth/elevation/range samples about a public reference origin. The shell
        is converted to ordinary ENU 3-D points, so all existing PTZ geometry and
        the control-center 3-D visualization remain unchanged.

    A cell is reset only when it is geometrically inside a ready camera FOV *and*
    the public virtual sensing model supplies enough pixels-on-target for discovery.
    This prevents a very wide low-zoom view from counting as an effective search
    observation at arbitrary range.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        research = cfg.policy.get("research", {})
        options = research.get("search", {})
        self.quality = SensingQualityModel(cfg)
        self.positions = self._build_positions(options, research, cfg)
        self.shape = tuple(int(x) for x in options.get("grid", [len(self.positions), 1, 1]))
        self.initial_age_s = float(options.get("initial_age_s", 0.0))
        self.age_cap_s = float(options.get("age_cap_s", 1e6))
        if self.initial_age_s < 0 or self.age_cap_s <= 0:
            raise ValueError("search ages must be non-negative and age_cap_s positive")
        if not len(self.positions):
            raise ValueError("persistent-search domain produced no cells")
        self.reset(0.0)

    @staticmethod
    def _network_centroid(cfg) -> np.ndarray:
        rows = np.asarray([d.position_m for d in cfg.active_devices], dtype=float)
        if rows.ndim != 2 or rows.shape[1] != 3 or not len(rows):
            raise ValueError("angular search domain requires at least one valid device position")
        return rows.mean(axis=0)

    def _build_positions(self, options, research, cfg) -> np.ndarray:
        domain = options.get("domain", {})
        kind = str(domain.get("type", "cartesian")).lower()
        shape = options.get("grid", [7, 7, 3])
        if len(shape) != 3 or any(int(n) != n or int(n) <= 0 for n in shape):
            raise ValueError("research.search.grid must contain three positive integers")
        shape = tuple(int(n) for n in shape)
        if kind in {"cartesian", "box"}:
            roi = options.get("roi", research.get("scenario", {}).get("roi", cfg.policy.get("roi")))
            if not roi:
                raise ValueError("cartesian persistent search needs an ROI")
            axes = [np.linspace(float(roi[k][0]), float(roi[k][1]), shape[i])
                    for i, k in enumerate(("x", "y", "z"))]
            return np.asarray(list(product(*axes)), dtype=float)
        if kind != "angular_shell":
            raise ValueError(f"unsupported research.search.domain.type: {kind!r}")

        origin_value = domain.get("origin_m", "network_centroid")
        origin = (self._network_centroid(cfg) if isinstance(origin_value, str) and origin_value == "network_centroid"
                  else np.asarray(origin_value, dtype=float))
        if origin.shape != (3,) or not np.all(np.isfinite(origin)):
            raise ValueError("angular search origin_m must be a finite 3-vector or network_centroid")
        az_range = domain.get("azimuth_deg", [-75.0, 75.0])
        el_range = domain.get("elevation_deg", [8.0, 38.0])
        range_value = domain.get("range_m", 170.0)
        if len(az_range) != 2 or len(el_range) != 2:
            raise ValueError("angular search azimuth/elevation ranges need [min,max]")
        if np.isscalar(range_value):
            ranges = np.full(shape[2], float(range_value), dtype=float)
        else:
            if len(range_value) != 2:
                raise ValueError("angular search range_m must be scalar or [min,max]")
            ranges = np.linspace(float(range_value[0]), float(range_value[1]), shape[2])
        if np.any(ranges <= 0):
            raise ValueError("angular search ranges must be positive")
        azimuths = np.deg2rad(np.linspace(float(az_range[0]), float(az_range[1]), shape[0]))
        elevations = np.deg2rad(np.linspace(float(el_range[0]), float(el_range[1]), shape[1]))
        points = []
        for az, el, radius in product(azimuths, elevations, ranges):
            ce = math.cos(float(el))
            direction = np.array([ce * math.cos(float(az)), ce * math.sin(float(az)), math.sin(float(el))])
            points.append(origin + float(radius) * direction)
        return np.asarray(points, dtype=float)

    def reset(self, t0: float = 0.0) -> None:
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
            geometric = np.fromiter((p is not None for p in projected), dtype=bool, count=len(projected))
            if not geometric.any():
                continue
            quality = np.fromiter(
                (self.quality.discovery_valid(point, config, float(state.zoom)) for point in self.positions),
                dtype=bool, count=len(self.positions),
            )
            observed |= geometric & quality
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
