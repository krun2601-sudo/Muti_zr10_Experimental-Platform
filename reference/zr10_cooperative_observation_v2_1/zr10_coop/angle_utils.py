from __future__ import annotations

from dataclasses import dataclass

from .config import DeviceConfig
from .types import AETarget


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def wrap_to_180(angle_deg: float) -> float:
    """Wrap an angle to [-180, 180)."""
    return (angle_deg + 180.0) % 360.0 - 180.0


def normalize_zr10_pitch(pitch_deg: float) -> float:
    """Normalize ZR10 pitch feedback that may wrap around +/-180 degrees."""
    if pitch_deg > 90.0:
        return pitch_deg - 180.0
    if pitch_deg < -90.0:
        return pitch_deg + 180.0
    return pitch_deg


@dataclass(frozen=True, slots=True)
class TransformedCommand:
    yaw_deg: float
    pitch_deg: float
    was_clamped: bool


class LocalAETransformer:
    """Map local AE commands to ZR10 yaw/pitch commands.

    This is intentionally isolated behind a class.  When the project moves to
    global ENU azimuth/elevation, replace this transformer with a calibrated
    3-D mount-pose transform while keeping the policy and device manager intact.
    """

    SUPPORTED_FRAME = "gimbal_local_ae"

    def __init__(self, config: DeviceConfig) -> None:
        self.config = config

    def to_gimbal(self, target: AETarget) -> TransformedCommand:
        if target.frame != self.SUPPORTED_FRAME:
            raise ValueError(
                f"Unsupported target frame {target.frame!r}; currently only "
                f"{self.SUPPORTED_FRAME!r} is implemented"
            )

        yaw_unclamped = (
            self.config.azimuth_to_yaw_sign * target.azimuth_deg
            + self.config.yaw_offset_deg
        )
        pitch_unclamped = (
            self.config.elevation_to_pitch_sign * target.elevation_deg
            + self.config.pitch_offset_deg
        )

        yaw = clamp(yaw_unclamped, self.config.yaw_min_deg, self.config.yaw_max_deg)
        pitch = clamp(
            pitch_unclamped,
            self.config.pitch_min_deg,
            self.config.pitch_max_deg,
        )
        was_clamped = abs(yaw - yaw_unclamped) > 1e-9 or abs(pitch - pitch_unclamped) > 1e-9
        return TransformedCommand(yaw_deg=yaw, pitch_deg=pitch, was_clamped=was_clamped)

    def from_gimbal(self, yaw_deg: float, pitch_deg: float) -> tuple[float, float]:
        azimuth = (yaw_deg - self.config.yaw_offset_deg) / self.config.azimuth_to_yaw_sign
        elevation = (
            pitch_deg - self.config.pitch_offset_deg
        ) / self.config.elevation_to_pitch_sign
        return azimuth, elevation
