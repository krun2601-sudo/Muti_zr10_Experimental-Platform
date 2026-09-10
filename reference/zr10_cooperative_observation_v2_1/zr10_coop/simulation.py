from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from .angle_utils import LocalAETransformer, wrap_to_180
from .config import DeviceConfig, SystemConfig
from .types import AETarget, CommandResult, GimbalFeedback, GimbalSnapshot


class SimulatedZR10Device:
    """First-order simulator for validating software without hardware."""

    def __init__(self, config: DeviceConfig, system: SystemConfig) -> None:
        self.config = config
        self.system = system
        self.transformer = LocalAETransformer(config)
        self.connected = False
        self.initialized = False
        self.initial_target_reached = False
        self.firmware = "SIM-0.2"
        self.motion_mode = "LOCK"
        self._azimuth = config.initial_azimuth_deg
        self._elevation = config.initial_elevation_deg
        self._target = AETarget(
            self._azimuth,
            self._elevation,
            source="simulation",
        )
        self._last_update = time.monotonic()
        self._feedback_sequence = 0
        self._command_sequence = 0
        self._last_command_monotonic = -math.inf
        self._last_command_yaw = None
        self._last_command_pitch = None
        self._last_yaw_speed = 0
        self._last_pitch_speed = 0
        self._last_error = ""

    @property
    def id(self) -> str:
        return self.config.id

    async def connect(self) -> None:
        self.connected = True

    async def reconnect(self) -> None:
        self.connected = True

    async def initialize(self) -> None:
        self.initialized = True
        self.initial_target_reached = True

    def _update(self) -> None:
        now = time.monotonic()
        dt = max(0.0, now - self._last_update)
        self._last_update = now
        max_rate = 35.0
        az_err = wrap_to_180(
            self._target.azimuth_deg - self._azimuth
        )
        el_err = (
            self._target.elevation_deg - self._elevation
        )
        az_step = max(
            -max_rate * dt,
            min(max_rate * dt, az_err),
        )
        el_step = max(
            -max_rate * dt,
            min(max_rate * dt, el_err),
        )
        self._azimuth += az_step
        self._elevation += el_step

    async def poll_feedback(
        self, force: bool = False
    ) -> None:
        self._update()

    async def send_target(
        self,
        target: AETarget,
        *,
        force=False,
        wait_for_ack=None,
    ) -> CommandResult:
        self._update()
        transformed = self.transformer.to_gimbal(target)
        now = time.monotonic()
        changed = (
            force
            or self._last_command_yaw is None
            or abs(
                transformed.yaw_deg
                - self._last_command_yaw
            )
            > self.system.command_change_threshold_deg
            or abs(
                transformed.pitch_deg
                - self._last_command_pitch
            )
            > self.system.command_change_threshold_deg
            or now - self._last_command_monotonic
            >= self.system.command_resend_interval_s
        )
        if changed:
            self._command_sequence += 1
            self._target = target
            self._last_command_yaw = (
                transformed.yaw_deg
            )
            self._last_command_pitch = (
                transformed.pitch_deg
            )
            self._last_command_monotonic = now
        complete = time.monotonic()
        return CommandResult(
            gimbal_id=self.id,
            target=target,
            command_yaw_deg=transformed.yaw_deg,
            command_pitch_deg=transformed.pitch_deg,
            was_clamped=transformed.was_clamped,
            sequence=self._command_sequence,
            sent=changed,
            status=(
                "simulated_ack"
                if changed
                else "held"
            ),
            start_monotonic_s=now,
            complete_monotonic_s=complete,
            latency_ms=(complete - now) * 1000.0,
            control_mode=self.config.control_mode,
            ack_received=changed,
            feedback_age_s=0.0,
        )

    async def wait_until_target(
        self, target, timeout_s, tolerance_deg
    ) -> bool:
        return True

    async def safe_stop(
        self, reliable: bool = True
    ) -> None:
        self._last_yaw_speed = 0
        self._last_pitch_speed = 0

    def snapshot(self) -> GimbalSnapshot:
        self._update()
        self._feedback_sequence += 1
        now = time.monotonic()
        local_ts = (
            datetime.now()
            .astimezone()
            .isoformat(timespec="milliseconds")
        )
        utc_ts = datetime.now(
            timezone.utc
        ).isoformat(timespec="milliseconds")
        transformed = self.transformer.to_gimbal(
            AETarget(
                self._azimuth,
                self._elevation,
                source="simulation_feedback",
            )
        )
        feedback = GimbalFeedback(
            timestamp_local=local_ts,
            timestamp_utc=utc_ts,
            monotonic_s=now,
            yaw_deg=transformed.yaw_deg,
            pitch_raw_deg=transformed.pitch_deg,
            pitch_deg=transformed.pitch_deg,
            roll_deg=0.0,
            azimuth_deg=self._azimuth,
            elevation_deg=self._elevation,
            yaw_rate_dps=0.0,
            pitch_rate_dps=0.0,
            roll_rate_dps=0.0,
            sequence=self._feedback_sequence,
            source="simulation",
        )
        return GimbalSnapshot(
            gimbal_id=self.id,
            name=self.config.name,
            ip=self.config.ip,
            connected=self.connected,
            initialized=self.initialized,
            initial_target_reached=(
                self.initial_target_reached
            ),
            firmware=self.firmware,
            motion_mode=self.motion_mode,
            feedback=feedback,
            feedback_age_s=0.0,
            feedback_stale=False,
            last_target=self._target,
            last_command_yaw_deg=(
                self._last_command_yaw
            ),
            last_command_pitch_deg=(
                self._last_command_pitch
            ),
            last_command_yaw_speed=(
                self._last_yaw_speed
            ),
            last_command_pitch_speed=(
                self._last_pitch_speed
            ),
            command_sequence=self._command_sequence,
            command_error_count=0,
            consecutive_command_errors=0,
            last_error=self._last_error,
        )

    async def close(
        self, *, center: bool | None = None
    ) -> None:
        self.connected = False
        self.initialized = False
