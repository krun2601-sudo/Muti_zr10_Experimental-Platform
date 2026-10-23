from __future__ import annotations

import math

import numpy as np

from ..geometry import intrinsics_at_zoom


class SensingQualityModel:
    """Auditable virtual image-quality model shared by every paper method.

    Geometric FOV inclusion is necessary but not sufficient for an effective
    observation.  A virtual target with public characteristic extent ``d_ref`` at
    range ``r`` has the small-object pinhole footprint approximation

        n_px = sqrt(fx * fy) * d_ref / r.

    ``discovery_min_pixels`` defines an effective search/detection observation and
    ``monitor_min_pixels`` defines the stricter continuous-monitoring observation.
    These are simulation sensing-model parameters, *not* measured ZR10 detector
    specifications.  They must be reported and sensitivity-tested.
    """

    def __init__(self, cfg):
        research = cfg.policy.get("research", {})
        options = research.get("sensing", {})
        self.reference_extent_m = float(options.get("reference_target_extent_m", 0.25))
        self.discovery_min_pixels = float(options.get("discovery_min_pixels", 6.0))
        self.monitor_min_pixels = float(options.get("monitor_min_pixels", 12.0))
        self.max_effective_range_m = float(options.get("max_effective_range_m", math.inf))
        if self.reference_extent_m <= 0:
            raise ValueError("research.sensing.reference_target_extent_m must be positive")
        if self.discovery_min_pixels <= 0 or self.monitor_min_pixels <= 0:
            raise ValueError("research sensing pixel thresholds must be positive")
        if self.monitor_min_pixels < self.discovery_min_pixels:
            raise ValueError("monitor_min_pixels must be >= discovery_min_pixels")
        if self.max_effective_range_m <= 0:
            raise ValueError("max_effective_range_m must be positive")

    def pixels_on_target(self, point, device, zoom: float) -> float:
        point = np.asarray(point, dtype=float)
        origin = np.asarray(device.position_m, dtype=float)
        if point.shape != (3,) or not np.all(np.isfinite(point)):
            return 0.0
        distance = float(np.linalg.norm(point - origin))
        if distance <= 1e-9 or distance > self.max_effective_range_m:
            return 0.0
        try:
            intrinsics = intrinsics_at_zoom(device, float(zoom))
        except ValueError:
            return 0.0
        focal = math.sqrt(float(intrinsics.fx) * float(intrinsics.fy))
        return float(focal * self.reference_extent_m / distance)

    def discovery_valid(self, point, device, zoom: float) -> bool:
        return self.pixels_on_target(point, device, zoom) + 1e-12 >= self.discovery_min_pixels

    def monitor_valid(self, point, device, zoom: float) -> bool:
        return self.pixels_on_target(point, device, zoom) + 1e-12 >= self.monitor_min_pixels

    def required_zoom_levels(self, point, device, zoom_levels, mode="discovery") -> list[float]:
        predicate = self.discovery_valid if mode == "discovery" else self.monitor_valid
        return [float(z) for z in zoom_levels if predicate(point, device, float(z))]
