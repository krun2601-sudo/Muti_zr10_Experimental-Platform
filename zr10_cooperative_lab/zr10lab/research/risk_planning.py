from __future__ import annotations

import math

import numpy as np

from ..geometry import mount_rotation, world_to_gimbal_angles
from .planning import PrimitiveFactory, PredictedTrack, _half_fov_deg, angle_delta_deg
from .sensing_quality import SensingQualityModel


class RiskAwarePrimitiveFactory(PrimitiveFactory):
    """Primitive factory with first-order A/E covariance and effective quality.

    For a predicted world position ``p ~ N(mu, P)``, the local gimbal coordinates
    are ``q = R_mount^T (p-o) = [x,y,z]``. The local pointing angles are

        A = atan2(y, x),
        E = atan2(z, sqrt(x^2+y^2)).

    Their analytic Jacobian is propagated through the world covariance to obtain
    separate ``sigma_A`` and ``sigma_E``. A two-sided Gaussian envelope is then
    combined with the configured inter-sample motion and fixed FOV margins.

    Geometric/risk containment is necessary but not sufficient: target-monitoring
    primitives must also meet the common virtual monitoring-quality threshold,
    while search-cell coverage must meet the discovery-quality threshold. Hence all
    paper methods face the same zoom/range sensing tradeoff.
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self.quality = SensingQualityModel(cfg)

    @staticmethod
    def angular_std_deg(point, covariance, device) -> tuple[float, float]:
        point = np.asarray(point, dtype=float)
        covariance = np.asarray(covariance, dtype=float)
        if point.shape != (3,) or covariance.shape != (3, 3):
            raise ValueError("point/covariance must have shapes (3,) and (3,3)")
        if not np.all(np.isfinite(point)) or not np.all(np.isfinite(covariance)):
            raise ValueError("point/covariance must be finite")
        covariance = 0.5 * (covariance + covariance.T)
        eig = np.linalg.eigvalsh(covariance)
        if eig.min() < -1e-8:
            raise ValueError("position covariance must be positive semidefinite")
        if eig.min() < 0:
            covariance = covariance + np.eye(3) * (-float(eig.min()) + 1e-12)

        r_mount = mount_rotation(device)
        q = r_mount.T @ (point - np.asarray(device.position_m, dtype=float))
        x, y, z = map(float, q)
        rho2 = x * x + y * y
        rho = math.sqrt(max(rho2, 0.0))
        r2 = rho2 + z * z
        if rho < 1e-8 or r2 < 1e-12:
            return 180.0, 180.0

        j_local = np.asarray([
            [-y / rho2, x / rho2, 0.0],
            [-z * x / (rho * r2), -z * y / (rho * r2), rho / r2],
        ], dtype=float)
        j_world = j_local @ r_mount.T
        angular_cov = j_world @ covariance @ j_world.T
        angular_cov = 0.5 * (angular_cov + angular_cov.T)
        variances = np.maximum(np.diag(angular_cov), 0.0)
        sigma_rad = np.sqrt(variances)
        return tuple(float(math.degrees(v)) for v in sigma_rad)

    def _visibility(self, device, yaw, pitch, zoom, ready_slot,
                    predicted: tuple[PredictedTrack, ...]) -> np.ndarray:
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
                    if self.use_uncertainty:
                        sigma_yaw, sigma_pitch = self.angular_std_deg(
                            point, track.covariances[h], device)
                    else:
                        sigma_yaw = sigma_pitch = 0.0
                except ValueError:
                    continue
                distance = max(float(np.linalg.norm(point - origin)), 1e-6)
                angular_speed = math.degrees(math.atan2(float(track.speeds[h]), distance))
                inter = angular_speed * self.slot_s * self.inter_sample_factor
                margin_yaw = kappa * sigma_yaw + inter + self.fov_margin_deg
                margin_pitch = kappa * sigma_pitch + inter + self.fov_margin_deg
                contained = (abs(angle_delta_deg(target_yaw, yaw)) + margin_yaw <= half_yaw and
                             abs(target_pitch - pitch) + margin_pitch <= half_pitch)
                if contained and self.quality.monitor_valid(point, device, zoom):
                    matrix[j, h] = True
        return matrix

    def _search_coverage(self, device, yaw, pitch, zoom, ready_slot, search_positions) -> np.ndarray:
        matrix = super()._search_coverage(device, yaw, pitch, zoom, ready_slot, search_positions)
        if not len(search_positions) or not matrix.any():
            return matrix
        quality = np.fromiter(
            (self.quality.discovery_valid(point, device, zoom) for point in search_positions),
            dtype=bool, count=len(search_positions),
        )
        matrix &= quality[:, None]
        return matrix
