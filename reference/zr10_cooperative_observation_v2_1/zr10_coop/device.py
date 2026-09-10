from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone
from typing import Any

from .angle_utils import LocalAETransformer, normalize_zr10_pitch, wrap_to_180
from .config import DeviceConfig, SystemConfig
from .types import AETarget, CommandResult, GimbalFeedback, GimbalSnapshot

try:
    from siyi_sdk import connect_udp
    from siyi_sdk.models import CaptureFuncType, DataStreamFreq, GimbalDataType
except ImportError as exc:  # pragma: no cover
    connect_udp = None
    CaptureFuncType = DataStreamFreq = GimbalDataType = None
    _SIYI_IMPORT_ERROR = exc
else:
    _SIYI_IMPORT_ERROR = None


FREQ_MAP = {2: "HZ2", 4: "HZ4", 5: "HZ5", 10: "HZ10", 20: "HZ20", 50: "HZ50", 100: "HZ100"}


def _timestamps() -> tuple[str, str]:
    return (
        datetime.now().astimezone().isoformat(timespec="milliseconds"),
        datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    )


def _quantize(value: int, quantum: int) -> int:
    if value == 0 or quantum <= 1:
        return value
    return int(round(value / quantum) * quantum)


def _p_speed(
    error_deg: float,
    kp: float,
    limit: int,
    minimum: int,
    deadband: float,
    quantum: int,
) -> int:
    if abs(error_deg) <= deadband:
        return 0
    value = int(round(kp * error_deg))
    if value == 0:
        value = 1 if error_deg > 0 else -1
    if abs(value) < minimum:
        value = minimum if value > 0 else -minimum
    value = _quantize(value, quantum)
    return max(-limit, min(limit, value))


class ZR10Device:
    """One ZR10 connection, feedback cache, and target-AE controller."""

    def __init__(self, config: DeviceConfig, system: SystemConfig) -> None:
        self.config = config
        self.system = system
        self.transformer = LocalAETransformer(config)
        self.client: Any = None
        self.connected = False
        self.initialized = False
        self.initial_target_reached = False
        self.firmware = ""
        self.motion_mode = ""

        self._latest_feedback: GimbalFeedback | None = None
        self._feedback_sequence = 0
        self._attitude_unsubscribe = None
        self._stream_active = False
        self._last_poll_monotonic = -math.inf

        self._last_target: AETarget | None = None
        self._last_command_yaw_deg: float | None = None
        self._last_command_pitch_deg: float | None = None
        self._last_command_monotonic = -math.inf
        self._last_yaw_speed: int | None = None
        self._last_pitch_speed: int | None = None
        self._command_sequence = 0
        self._command_error_count = 0
        self._consecutive_command_errors = 0
        self._last_error = ""

    @property
    def id(self) -> str:
        return self.config.id

    def _reset_session_state(self) -> None:
        self.connected = False
        self.initialized = False
        self.initial_target_reached = False
        self.firmware = ""
        self.motion_mode = ""
        self._latest_feedback = None
        self._feedback_sequence = 0
        self._attitude_unsubscribe = None
        self._stream_active = False
        self._last_poll_monotonic = -math.inf
        self._last_target = None
        self._last_command_yaw_deg = None
        self._last_command_pitch_deg = None
        self._last_command_monotonic = -math.inf
        self._last_yaw_speed = None
        self._last_pitch_speed = None
        self._consecutive_command_errors = 0
        self._last_error = ""

    async def connect(self) -> None:
        if connect_udp is None:
            raise RuntimeError(
                "siyi_sdk is not installed. Install the local SDK with "
                "python -m pip install -e /path/to/siyi_sdk-siyi-sdk-v2"
            ) from _SIYI_IMPORT_ERROR

        self._reset_session_state()
        self.client = await connect_udp(
            self.config.ip,
            self.config.control_port,
            timeout=self.config.command_timeout_s,
            max_retries=self.config.max_retries,
            auto_reconnect=False,
        )
        try:
            firmware = await self.client.get_firmware_version()
            self.firmware = str(firmware)
            self.connected = True

            # ACK-bearing stop is deliberate. Older ZR10 firmware may silently
            # ignore fire-and-forget movement frames.
            if self.system.startup_stop_motion:
                await self.safe_stop(reliable=True)

            if self.system.startup_clear_attitude_stream:
                try:
                    await self.client.request_gimbal_stream(
                        GimbalDataType.ATTITUDE, DataStreamFreq.OFF
                    )
                except Exception as exc:
                    self._last_error = (
                        f"clear old attitude stream warning: "
                        f"{type(exc).__name__}: {exc}"
                    )

            await asyncio.sleep(self.system.startup_connection_settle_s)
            self._attitude_unsubscribe = self.client.on_attitude(self._on_attitude_stream)
            freq = getattr(DataStreamFreq, FREQ_MAP[self.system.attitude_stream_hz])
            try:
                await self.client.request_gimbal_stream(GimbalDataType.ATTITUDE, freq)
                self._stream_active = True
            except Exception as exc:
                self._stream_active = False
                self._last_error = (
                    f"attitude stream unavailable; polling fallback enabled: "
                    f"{type(exc).__name__}: {exc}"
                )

            await self.wait_for_fresh_feedback(self.system.fresh_feedback_timeout_s)
        except Exception:
            await self._close_transport_only()
            raise

    async def reconnect(self) -> None:
        await self.close(center=False)
        await asyncio.sleep(self.system.initialization_retry_delay_s)
        await self.connect()

    async def initialize(self) -> None:
        if not self.connected or self.client is None:
            raise RuntimeError(f"{self.id} is not connected")

        if self.system.startup_lock_mode:
            try:
                await self.client.capture(CaptureFuncType.LOCK_MODE)
                await asyncio.sleep(0.25)
                try:
                    mode = await self.client.get_gimbal_mode()
                    self.motion_mode = getattr(mode, "name", str(mode))
                except Exception as exc:
                    self._last_error = f"mode query warning: {type(exc).__name__}: {exc}"
            except Exception as exc:
                message = f"lock-mode command failed: {type(exc).__name__}: {exc}"
                if self.system.startup_lock_required:
                    raise RuntimeError(message) from exc
                self._last_error = message

        if self.system.startup_center:
            await self.client.one_key_centering()
            await asyncio.sleep(self.system.startup_center_settle_s)
            await self.wait_for_fresh_feedback(self.system.fresh_feedback_timeout_s)

        self.initialized = True
        if not self.system.startup_move_to_initial:
            return

        initial = AETarget(
            azimuth_deg=self.config.initial_azimuth_deg,
            elevation_deg=self.config.initial_elevation_deg,
            source="startup_initialization",
        )
        reached = await self.move_to_target(
            initial,
            timeout_s=self.system.startup_initial_settle_timeout_s,
            tolerance_deg=self.system.target_tolerance_deg,
            progress_label="INIT",
        )
        self.initial_target_reached = reached
        if not reached and self.system.startup_initial_required:
            raise RuntimeError(
                f"{self.id} could not reach initial AE "
                f"({initial.azimuth_deg:.1f}, {initial.elevation_deg:.1f}); "
                f"last_error={self._last_error or 'none'}"
            )

    def _on_attitude_stream(self, attitude: Any) -> None:
        self._store_attitude(attitude, source="stream")

    def _store_attitude(self, attitude: Any, source: str) -> None:
        now = time.monotonic()
        pitch_raw = float(attitude.pitch_deg)
        pitch = (
            normalize_zr10_pitch(pitch_raw)
            if self.config.normalize_pitch_feedback
            else pitch_raw
        )
        azimuth, elevation = self.transformer.from_gimbal(float(attitude.yaw_deg), pitch)
        self._feedback_sequence += 1
        local_ts, utc_ts = _timestamps()
        self._latest_feedback = GimbalFeedback(
            timestamp_local=local_ts,
            timestamp_utc=utc_ts,
            monotonic_s=now,
            yaw_deg=float(attitude.yaw_deg),
            pitch_raw_deg=pitch_raw,
            pitch_deg=pitch,
            roll_deg=float(attitude.roll_deg),
            azimuth_deg=azimuth,
            elevation_deg=elevation,
            yaw_rate_dps=float(attitude.yaw_rate_dps),
            pitch_rate_dps=float(attitude.pitch_rate_dps),
            roll_rate_dps=float(attitude.roll_rate_dps),
            sequence=self._feedback_sequence,
            source=source,
        )

    async def wait_for_fresh_feedback(self, timeout_s: float) -> GimbalFeedback:
        deadline = time.monotonic() + timeout_s
        last_error = ""
        while time.monotonic() < deadline:
            await self.poll_feedback(force=True)
            feedback = self._latest_feedback
            if (
                feedback is not None
                and time.monotonic() - feedback.monotonic_s <= self.system.feedback_stale_s
            ):
                return feedback
            last_error = self._last_error
            await asyncio.sleep(0.12)
        raise RuntimeError(
            f"{self.id} did not provide fresh attitude feedback within {timeout_s:.1f}s; "
            f"last_error={last_error or 'none'}"
        )

    async def poll_feedback(self, force: bool = False) -> None:
        if not self.connected or self.client is None:
            return
        now = time.monotonic()
        age = (
            math.inf
            if self._latest_feedback is None
            else now - self._latest_feedback.monotonic_s
        )
        due = now - self._last_poll_monotonic >= self.system.fallback_poll_interval_s
        if not force and self._stream_active and age <= self.system.feedback_stale_s:
            return
        if not force and not due:
            return
        self._last_poll_monotonic = now
        try:
            attitude = await self.client.get_gimbal_attitude()
            self._store_attitude(attitude, source="poll")
        except Exception as exc:
            self._last_error = f"feedback polling failed: {type(exc).__name__}: {exc}"

    def _should_send_position(self, yaw_deg: float, pitch_deg: float, force: bool) -> bool:
        if force or self._last_command_yaw_deg is None or self._last_command_pitch_deg is None:
            return True
        changed = (
            abs(wrap_to_180(yaw_deg - self._last_command_yaw_deg))
            > self.system.command_change_threshold_deg
            or abs(pitch_deg - self._last_command_pitch_deg)
            > self.system.command_change_threshold_deg
        )
        resend_due = (
            time.monotonic() - self._last_command_monotonic
            >= self.system.command_resend_interval_s
        )
        return changed or resend_due

    async def send_target(
        self,
        target: AETarget,
        *,
        force: bool = False,
        wait_for_ack: bool | None = None,
    ) -> CommandResult:
        if not self.connected or self.client is None:
            return self._not_connected_result(target)

        await self.poll_feedback(force=False)
        feedback = self._latest_feedback
        feedback_age = (
            None if feedback is None else time.monotonic() - feedback.monotonic_s
        )
        if (
            feedback is None
            or feedback_age is None
            or feedback_age > self.system.feedback_stale_s
        ):
            await self.safe_stop(reliable=False)
            transformed = self.transformer.to_gimbal(target)
            return self._command_error(
                target,
                transformed,
                time.monotonic(),
                self.config.control_mode,
                RuntimeError(f"stale/no feedback (age={feedback_age})"),
                feedback_age=feedback_age,
            )

        transformed = self.transformer.to_gimbal(target)
        if self.config.control_mode == "velocity_p":
            return await self._send_velocity_p(target, transformed, force=force)
        return await self._send_position(
            target, transformed, force=force, wait_for_ack=wait_for_ack
        )

    def _not_connected_result(self, target: AETarget) -> CommandResult:
        now = time.monotonic()
        return CommandResult(
            gimbal_id=self.id,
            target=target,
            command_yaw_deg=float("nan"),
            command_pitch_deg=float("nan"),
            was_clamped=False,
            sequence=self._command_sequence,
            sent=False,
            status="not_connected",
            start_monotonic_s=now,
            complete_monotonic_s=now,
            latency_ms=0.0,
            control_mode=self.config.control_mode,
            error="device not connected",
        )

    async def _send_position(
        self, target, transformed, *, force, wait_for_ack
    ) -> CommandResult:
        now = time.monotonic()
        if not self._should_send_position(
            transformed.yaw_deg, transformed.pitch_deg, force
        ):
            self._last_target = target
            return CommandResult(
                gimbal_id=self.id,
                target=target,
                command_yaw_deg=transformed.yaw_deg,
                command_pitch_deg=transformed.pitch_deg,
                was_clamped=transformed.was_clamped,
                sequence=self._command_sequence,
                sent=False,
                status="position_held",
                start_monotonic_s=now,
                complete_monotonic_s=now,
                latency_ms=0.0,
                control_mode="position",
                feedback_age_s=self._feedback_age(),
            )

        self._command_sequence += 1
        start = time.monotonic()
        ack_yaw = ack_pitch = ack_roll = None
        use_ack = (
            self.system.command_wait_for_ack
            if wait_for_ack is None
            else wait_for_ack
        )
        try:
            if use_ack:
                ack = await self.client.set_attitude(
                    transformed.yaw_deg, transformed.pitch_deg
                )
                ack_yaw = float(ack.yaw_deg)
                ack_pitch = float(ack.pitch_deg)
                ack_roll = float(ack.roll_deg)
                status = "position_acknowledged"
                ack_received = True
            else:
                await self.client.set_attitude_nowait(
                    transformed.yaw_deg, transformed.pitch_deg
                )
                status = "position_sent_nowait"
                ack_received = False
            complete = time.monotonic()
            self._remember_success(
                target, transformed.yaw_deg, transformed.pitch_deg, complete
            )
            return CommandResult(
                gimbal_id=self.id,
                target=target,
                command_yaw_deg=transformed.yaw_deg,
                command_pitch_deg=transformed.pitch_deg,
                was_clamped=transformed.was_clamped,
                sequence=self._command_sequence,
                sent=True,
                status=status,
                start_monotonic_s=start,
                complete_monotonic_s=complete,
                latency_ms=(complete - start) * 1000.0,
                control_mode="position",
                ack_received=ack_received,
                ack_yaw_deg=ack_yaw,
                ack_pitch_deg=ack_pitch,
                ack_roll_deg=ack_roll,
                feedback_age_s=self._feedback_age(),
            )
        except Exception as exc:
            return self._command_error(
                target, transformed, start, "position", exc
            )

    async def _send_velocity_p(self, target, transformed, *, force) -> CommandResult:
        start = time.monotonic()
        feedback = self._latest_feedback
        if feedback is None:
            return self._command_error(
                target,
                transformed,
                start,
                "velocity_p",
                RuntimeError("no attitude feedback available"),
            )

        yaw_error = wrap_to_180(transformed.yaw_deg - feedback.yaw_deg)
        pitch_error = transformed.pitch_deg - feedback.pitch_deg
        yaw_speed_raw = _p_speed(
            yaw_error,
            self.config.yaw_kp,
            self.config.yaw_speed_limit,
            self.config.minimum_speed,
            self.config.control_deadband_deg,
            self.config.speed_quantization,
        )
        pitch_speed_raw = _p_speed(
            pitch_error,
            self.config.pitch_kp,
            self.config.pitch_speed_limit,
            self.config.minimum_speed,
            self.config.control_deadband_deg,
            self.config.speed_quantization,
        )

        # IMPORTANT: the sign of an SDK velocity command is not necessarily
        # the same as the sign of the reported yaw/pitch angle.  On the tested
        # ZR10 units, positive pitch velocity decreases the reported pitch.
        # Direction signs are therefore calibrated independently per device.
        yaw_speed = int(self.config.yaw_velocity_sign * yaw_speed_raw)
        pitch_speed = int(self.config.pitch_velocity_sign * pitch_speed_raw)

        same_speed = (
            yaw_speed == self._last_yaw_speed
            and pitch_speed == self._last_pitch_speed
        )
        resend_due = (
            time.monotonic() - self._last_command_monotonic
            >= self.system.command_resend_interval_s
        )
        should_send = force or not same_speed or resend_due
        self._last_target = target
        if not should_send:
            complete = time.monotonic()
            return CommandResult(
                gimbal_id=self.id,
                target=target,
                command_yaw_deg=transformed.yaw_deg,
                command_pitch_deg=transformed.pitch_deg,
                was_clamped=transformed.was_clamped,
                sequence=self._command_sequence,
                sent=False,
                status="velocity_held",
                start_monotonic_s=start,
                complete_monotonic_s=complete,
                latency_ms=(complete - start) * 1000.0,
                control_mode="velocity_p",
                yaw_error_deg=yaw_error,
                pitch_error_deg=pitch_error,
                command_yaw_speed=yaw_speed,
                command_pitch_speed=pitch_speed,
                feedback_age_s=self._feedback_age(),
            )

        self._command_sequence += 1
        ack_received = False
        fallback_used = False
        warning = ""
        try:
            if self.config.velocity_use_ack:
                try:
                    await self.client.rotate(yaw=yaw_speed, pitch=pitch_speed)
                    ack_received = True
                    status = "velocity_acknowledged"
                except Exception as ack_exc:
                    if not self.config.velocity_ack_fallback_nowait:
                        raise
                    await self.client.rotate_nowait(
                        yaw=yaw_speed, pitch=pitch_speed
                    )
                    fallback_used = True
                    status = "velocity_fallback_nowait"
                    warning = (
                        f"ACK failed, fallback sent: "
                        f"{type(ack_exc).__name__}: {ack_exc}"
                    )
                    self._command_error_count += 1
            else:
                await self.client.rotate_nowait(yaw=yaw_speed, pitch=pitch_speed)
                status = "velocity_sent_nowait"

            complete = time.monotonic()
            self._last_yaw_speed = yaw_speed
            self._last_pitch_speed = pitch_speed
            self._last_target = target
            self._last_command_yaw_deg = transformed.yaw_deg
            self._last_command_pitch_deg = transformed.pitch_deg
            self._last_command_monotonic = complete
            if fallback_used:
                self._consecutive_command_errors += 1
                self._last_error = warning
            else:
                self._consecutive_command_errors = 0
                self._last_error = ""
            if yaw_speed == 0 and pitch_speed == 0:
                status = "on_target_stop_ack" if ack_received else "on_target_stop"
            return CommandResult(
                gimbal_id=self.id,
                target=target,
                command_yaw_deg=transformed.yaw_deg,
                command_pitch_deg=transformed.pitch_deg,
                was_clamped=transformed.was_clamped,
                sequence=self._command_sequence,
                sent=True,
                status=status,
                start_monotonic_s=start,
                complete_monotonic_s=complete,
                latency_ms=(complete - start) * 1000.0,
                control_mode="velocity_p",
                yaw_error_deg=yaw_error,
                pitch_error_deg=pitch_error,
                command_yaw_speed=yaw_speed,
                command_pitch_speed=pitch_speed,
                ack_received=ack_received,
                fallback_used=fallback_used,
                feedback_age_s=self._feedback_age(),
                error=warning,
            )
        except Exception as exc:
            return self._command_error(
                target,
                transformed,
                start,
                "velocity_p",
                exc,
                yaw_error=yaw_error,
                pitch_error=pitch_error,
                yaw_speed=yaw_speed,
                pitch_speed=pitch_speed,
            )

    def _feedback_age(self) -> float | None:
        if self._latest_feedback is None:
            return None
        return max(0.0, time.monotonic() - self._latest_feedback.monotonic_s)

    def _remember_success(self, target, yaw_deg, pitch_deg, complete) -> None:
        self._last_target = target
        self._last_command_yaw_deg = yaw_deg
        self._last_command_pitch_deg = pitch_deg
        self._last_command_monotonic = complete
        self._consecutive_command_errors = 0
        self._last_error = ""

    def _command_error(
        self,
        target,
        transformed,
        start,
        control_mode,
        exc,
        *,
        yaw_error=None,
        pitch_error=None,
        yaw_speed=None,
        pitch_speed=None,
        feedback_age=None,
    ) -> CommandResult:
        complete = time.monotonic()
        self._command_error_count += 1
        self._consecutive_command_errors += 1
        self._last_error = f"command failed: {type(exc).__name__}: {exc}"
        return CommandResult(
            gimbal_id=self.id,
            target=target,
            command_yaw_deg=transformed.yaw_deg,
            command_pitch_deg=transformed.pitch_deg,
            was_clamped=transformed.was_clamped,
            sequence=self._command_sequence,
            sent=False,
            status="error",
            start_monotonic_s=start,
            complete_monotonic_s=complete,
            latency_ms=(complete - start) * 1000.0,
            control_mode=control_mode,
            yaw_error_deg=yaw_error,
            pitch_error_deg=pitch_error,
            command_yaw_speed=yaw_speed,
            command_pitch_speed=pitch_speed,
            feedback_age_s=(
                feedback_age if feedback_age is not None else self._feedback_age()
            ),
            error=self._last_error,
        )

    async def move_to_target(
        self,
        target: AETarget,
        timeout_s: float,
        tolerance_deg: float,
        progress_label: str = "MOVE",
    ) -> bool:
        deadline = time.monotonic() + timeout_s
        next_progress = 0.0
        first = True
        while time.monotonic() < deadline:
            await self.poll_feedback(force=False)
            result = await self.send_target(
                target, force=first, wait_for_ack=True
            )
            first = False
            feedback = self._latest_feedback

            if feedback is not None:
                az_err = wrap_to_180(
                    target.azimuth_deg - feedback.azimuth_deg
                )
                el_err = target.elevation_deg - feedback.elevation_deg
                error_norm = math.hypot(az_err, el_err)
                now = time.monotonic()
                if now >= next_progress:
                    print(
                        f"[{progress_label}] {self.id} {self.config.ip} "
                        f"target={target.azimuth_deg:+.1f}/{target.elevation_deg:+.1f} "
                        f"actual={feedback.azimuth_deg:+.1f}/{feedback.elevation_deg:+.1f} "
                        f"err={az_err:+.1f}/{el_err:+.1f} "
                        f"speed={result.command_yaw_speed}/{result.command_pitch_speed} "
                        f"status={result.status}",
                        flush=True,
                    )
                    next_progress = (
                        now + self.system.startup_progress_interval_s
                    )
                if error_norm <= tolerance_deg:
                    await self.safe_stop(reliable=True)
                    return True

            if (
                result.status == "error"
                and self._consecutive_command_errors
                >= self.system.max_consecutive_command_errors
            ):
                await self.safe_stop(reliable=False)
                return False
            await asyncio.sleep(
                1.0 / max(2.0, self.system.control_rate_hz)
            )

        self._last_error = (
            f"target not reached within {timeout_s:.1f}s: "
            f"az={target.azimuth_deg:.1f}, el={target.elevation_deg:.1f}; "
            f"last_feedback="
            f"{None if self._latest_feedback is None else (self._latest_feedback.azimuth_deg, self._latest_feedback.elevation_deg)}"
        )
        await self.safe_stop(reliable=True)
        return False

    async def wait_until_target(
        self, target: AETarget, timeout_s: float, tolerance_deg: float
    ) -> bool:
        return await self.move_to_target(target, timeout_s, tolerance_deg)

    async def safe_stop(self, reliable: bool = True) -> None:
        if self.client is None:
            return
        last_exc: Exception | None = None
        for _ in range(self.system.stop_command_repetitions):
            try:
                if reliable:
                    await self.client.rotate(yaw=0, pitch=0)
                else:
                    await self.client.rotate_nowait(yaw=0, pitch=0)
                last_exc = None
            except Exception as exc:
                last_exc = exc
                try:
                    await self.client.rotate_nowait(yaw=0, pitch=0)
                except Exception:
                    pass
            await asyncio.sleep(self.system.stop_command_interval_s)
        self._last_yaw_speed = 0
        self._last_pitch_speed = 0
        if last_exc is not None:
            self._last_error = (
                f"stop warning: {type(last_exc).__name__}: {last_exc}"
            )

    def snapshot(self) -> GimbalSnapshot:
        age = self._feedback_age()
        return GimbalSnapshot(
            gimbal_id=self.id,
            name=self.config.name,
            ip=self.config.ip,
            connected=self.connected,
            initialized=self.initialized,
            initial_target_reached=self.initial_target_reached,
            firmware=self.firmware,
            motion_mode=self.motion_mode,
            feedback=self._latest_feedback,
            feedback_age_s=age,
            feedback_stale=(
                age is None or age > self.system.feedback_stale_s
            ),
            last_target=self._last_target,
            last_command_yaw_deg=self._last_command_yaw_deg,
            last_command_pitch_deg=self._last_command_pitch_deg,
            last_command_yaw_speed=self._last_yaw_speed,
            last_command_pitch_speed=self._last_pitch_speed,
            command_sequence=self._command_sequence,
            command_error_count=self._command_error_count,
            consecutive_command_errors=self._consecutive_command_errors,
            last_error=self._last_error,
        )

    async def _close_transport_only(self) -> None:
        if self._attitude_unsubscribe:
            try:
                self._attitude_unsubscribe()
            except Exception:
                pass
            self._attitude_unsubscribe = None
        if self.client is not None:
            try:
                await self.client.close()
            except Exception:
                pass
        self.client = None
        self.connected = False
        self.initialized = False

    async def close(self, *, center: bool | None = None) -> None:
        if self.client is None:
            return
        do_center = (
            self.system.center_on_shutdown if center is None else center
        )
        try:
            await self.safe_stop(reliable=True)
            if do_center and self.connected:
                await self.client.one_key_centering()
                await asyncio.sleep(self.system.startup_center_settle_s)
            if self._stream_active:
                try:
                    await self.client.request_gimbal_stream(
                        GimbalDataType.ATTITUDE, DataStreamFreq.OFF
                    )
                except Exception:
                    pass
        finally:
            await self._close_transport_only()
            await asyncio.sleep(self.system.shutdown_settle_s)
