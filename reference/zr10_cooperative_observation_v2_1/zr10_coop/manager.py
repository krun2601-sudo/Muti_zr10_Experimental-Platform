from __future__ import annotations

import asyncio
import json
import math
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .angle_utils import wrap_to_180
from .config import AppConfig
from .csv_logger import CsvSessionLogger
from .device import ZR10Device
from .observation import NullObservationProvider, ObservationProvider
from .policies.base import CooperativePolicy
from .simulation import SimulatedZR10Device
from .types import AETarget, CommandResult, GimbalSnapshot, PolicyContext


def _wall_timestamps() -> tuple[str, str]:
    return (
        datetime.now().astimezone().isoformat(timespec="milliseconds"),
        datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    )


class CooperativeObservationSystem:
    def __init__(
        self,
        config: AppConfig,
        policy: CooperativePolicy,
        *,
        dry_run: bool = False,
        observation_provider: ObservationProvider | None = None,
    ) -> None:
        self.config = config
        self.policy = policy
        self.dry_run = dry_run
        self.observation_provider = (
            observation_provider or NullObservationProvider()
        )

        device_cls = SimulatedZR10Device if dry_run else ZR10Device
        self.devices = {
            item.id: device_cls(item, config.system)
            for item in config.enabled_gimbals()
        }

        config_dir = Path(config.source_path).parent
        log_root = Path(config.system.log_root)
        if not log_root.is_absolute():
            log_root = (config_dir.parent / log_root).resolve()
        self.logger = CsvSessionLogger(
            log_root=log_root,
            session_name=config.system.session_name,
            queue_size=config.system.csv_queue_size,
            flush_interval_s=config.system.csv_flush_interval_s,
        )
        self._stop_event = asyncio.Event()
        self._run_start_monotonic = 0.0
        self._control_start_monotonic = 0.0

    async def run(self) -> Path:
        self.logger.start(
            self.config.as_dict(),
            extra_metadata={
                "dry_run": self.dry_run,
                "policy_name": self.policy.name,
                "device_count": len(self.devices),
            },
        )
        self._install_signal_handlers()
        self._run_start_monotonic = time.monotonic()
        self._event(
            "INFO",
            "session_start",
            message="cooperative observation session started",
        )

        primary_error: BaseException | None = None
        try:
            await self.observation_provider.initialize()
            await self._connect_all()
            await self._initialize_all()
            await self.policy.initialize(tuple(self.devices.keys()))
            await self._control_loop()
        except BaseException as exc:
            primary_error = exc
            self._event(
                "ERROR",
                "session_exception",
                message=f"{type(exc).__name__}: {exc}",
            )
        finally:
            await self._shutdown_all()
            try:
                await self.policy.close()
            except Exception as exc:
                self._event(
                    "WARNING", "policy_close_failed", message=str(exc)
                )
            try:
                await self.observation_provider.close()
            except Exception as exc:
                self._event(
                    "WARNING",
                    "observation_close_failed",
                    message=str(exc),
                )
            self._event("INFO", "session_end", message="session ended")
            self.logger.close()

        if primary_error is not None:
            raise primary_error
        return self.logger.session_dir

    def request_stop(self) -> None:
        self._stop_event.set()

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.request_stop)
            except NotImplementedError:
                pass

    async def _connect_all(self) -> None:
        """Connect sequentially to avoid a multi-device UDP request burst."""
        failures: dict[str, str] = {}
        devices = list(self.devices.values())

        for index, device in enumerate(devices):
            errors: list[str] = []
            connected = False
            for attempt in range(
                1, self.config.system.connect_attempts + 1
            ):
                try:
                    await device.connect()
                    snapshot = device.snapshot()
                    self._event(
                        "INFO",
                        "connected",
                        gimbal_id=device.id,
                        message=(
                            f"{snapshot.name} connected at {snapshot.ip}"
                        ),
                        details={"firmware": snapshot.firmware},
                    )
                    print(
                        f"[CONNECTED] {device.id} {device.config.ip} "
                        f"firmware={snapshot.firmware}",
                        flush=True,
                    )
                    connected = True
                    break
                except Exception as exc:
                    message = (
                        f"attempt {attempt}: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    errors.append(message)
                    self._event(
                        (
                            "WARNING"
                            if attempt
                            < self.config.system.connect_attempts
                            else "ERROR"
                        ),
                        "connect_attempt_failed",
                        gimbal_id=device.id,
                        message=message,
                    )
                    print(
                        f"[CONNECT RETRY] {device.id} "
                        f"{device.config.ip}: {message}",
                        flush=True,
                    )
                    try:
                        await device.close(center=False)
                    except Exception:
                        pass
                    if attempt < self.config.system.connect_attempts:
                        await asyncio.sleep(
                            self.config.system.connect_retry_delay_s
                        )

            if not connected:
                failures[device.id] = "; ".join(errors)
            if index < len(devices) - 1:
                await asyncio.sleep(
                    self.config.system.connect_stagger_s
                )

        if failures and self.config.system.require_all_devices:
            raise RuntimeError(
                f"Required gimbals failed to connect: {failures}"
            )

    async def _initialize_all(self) -> None:
        online = [
            device
            for device in self.devices.values()
            if device.snapshot().connected
        ]
        results = await asyncio.gather(
            *(
                self._initialize_one_with_retry(device)
                for device in online
            ),
            return_exceptions=True,
        )
        failures: dict[str, str] = {}
        for device, result in zip(online, results):
            if isinstance(result, Exception):
                reason = f"{type(result).__name__}: {result}"
                failures[device.id] = reason
                self._event(
                    "ERROR",
                    "initialization_failed",
                    gimbal_id=device.id,
                    message=reason,
                )
                print(
                    f"[INIT FAILED] {device.id} "
                    f"({device.config.ip}): {reason}",
                    flush=True,
                )
            else:
                snapshot = device.snapshot()
                self._event(
                    (
                        "INFO"
                        if snapshot.initial_target_reached
                        else "WARNING"
                    ),
                    "initialized",
                    gimbal_id=device.id,
                    message=(
                        "initial target reached="
                        f"{snapshot.initial_target_reached}"
                    ),
                )

        if failures and self.config.system.require_all_devices:
            raise RuntimeError(
                f"Required gimbals failed to initialize: {failures}"
            )

    async def _initialize_one_with_retry(
        self, device: ZR10Device
    ) -> None:
        attempts = self.config.system.initialization_attempts
        errors: list[str] = []
        for attempt in range(1, attempts + 1):
            try:
                await device.initialize()
                if attempt > 1:
                    self._event(
                        "INFO",
                        "initialization_recovered",
                        gimbal_id=device.id,
                        message=(
                            "initialized successfully on "
                            f"attempt {attempt}"
                        ),
                    )
                return
            except Exception as exc:
                message = (
                    f"attempt {attempt}/{attempts}: "
                    f"{type(exc).__name__}: {exc}"
                )
                errors.append(message)
                self._event(
                    (
                        "WARNING"
                        if attempt < attempts
                        else "ERROR"
                    ),
                    "initialization_attempt_failed",
                    gimbal_id=device.id,
                    message=message,
                )
                print(
                    f"[INIT RETRY] {device.id} "
                    f"({device.config.ip}) {message}",
                    flush=True,
                )
                if attempt >= attempts:
                    break
                try:
                    await device.reconnect()
                except Exception as reconnect_exc:
                    reconnect_message = (
                        f"reconnect after attempt {attempt} failed: "
                        f"{type(reconnect_exc).__name__}: "
                        f"{reconnect_exc}"
                    )
                    errors.append(reconnect_message)
                    print(
                        f"[RECONNECT FAILED] {device.id}: "
                        f"{reconnect_message}",
                        flush=True,
                    )
        raise RuntimeError("; ".join(errors))

    async def _control_loop(self) -> None:
        period_s = 1.0 / self.config.system.control_rate_hz
        start = time.monotonic()
        self._control_start_monotonic = start
        next_tick = start
        cycle_index = 0
        previous_phase: str | None = None

        while not self._stop_event.is_set():
            now = time.monotonic()
            elapsed = now - start
            if (
                self.config.system.duration_s > 0
                and elapsed >= self.config.system.duration_s
            ):
                break

            poll_results = await asyncio.gather(
                *(
                    device.poll_feedback(force=False)
                    for device in self.devices.values()
                ),
                return_exceptions=True,
            )
            for device, result in zip(
                self.devices.values(), poll_results
            ):
                if isinstance(result, Exception):
                    self._event(
                        "WARNING",
                        "feedback_poll_exception",
                        gimbal_id=device.id,
                        message=(
                            f"{type(result).__name__}: {result}"
                        ),
                    )

            states_before = {
                device_id: device.snapshot()
                for device_id, device in self.devices.items()
            }
            observations = (
                await self.observation_provider.collect(
                    elapsed, states_before
                )
            )
            decision = self.policy.compute(
                PolicyContext(
                    elapsed_s=elapsed,
                    cycle_index=cycle_index,
                    device_states=states_before,
                    observations=observations,
                )
            )
            targets = self._validate_policy_output(
                decision.targets, states_before
            )

            phase_changed = (
                previous_phase is None
                or decision.phase != previous_phase
            )
            previous_phase = decision.phase
            batch_start = time.monotonic()

            command_results_list = await asyncio.gather(
                *(
                    self.devices[device_id].send_target(
                        target,
                        force=(
                            cycle_index == 0 or phase_changed
                        ),
                    )
                    for device_id, target in targets.items()
                ),
                return_exceptions=True,
            )

            command_results: dict[str, CommandResult] = {}
            fatal_errors: list[str] = []
            for device_id, raw_result in zip(
                targets.keys(), command_results_list
            ):
                if isinstance(raw_result, Exception):
                    target = targets[device_id]
                    result = CommandResult(
                        gimbal_id=device_id,
                        target=target,
                        command_yaw_deg=float("nan"),
                        command_pitch_deg=float("nan"),
                        was_clamped=False,
                        sequence=0,
                        sent=False,
                        status="exception",
                        start_monotonic_s=batch_start,
                        complete_monotonic_s=time.monotonic(),
                        latency_ms=0.0,
                        control_mode=(
                            self.devices[
                                device_id
                            ].config.control_mode
                        ),
                        error=(
                            f"{type(raw_result).__name__}: "
                            f"{raw_result}"
                        ),
                    )
                else:
                    result = raw_result

                command_results[device_id] = result
                if result.status in {"error", "exception"}:
                    self._event(
                        "ERROR",
                        "command_failed",
                        gimbal_id=device_id,
                        message=result.error,
                    )
                    snapshot = self.devices[
                        device_id
                    ].snapshot()
                    if (
                        not self.config.system.continue_on_command_error
                        or snapshot.consecutive_command_errors
                        >= self.config.system.max_consecutive_command_errors
                    ):
                        fatal_errors.append(
                            f"{device_id}: {result.error}"
                        )
                elif result.fallback_used:
                    self._event(
                        "WARNING",
                        "command_ack_fallback",
                        gimbal_id=device_id,
                        message=result.error,
                    )

            states_after = {
                device_id: device.snapshot()
                for device_id, device in self.devices.items()
            }
            self._log_cycle(
                elapsed_s=elapsed,
                cycle_index=cycle_index,
                policy_phase=decision.phase,
                policy_diagnostics=decision.diagnostics,
                targets=targets,
                command_results=command_results,
                states=states_after,
                batch_start_monotonic=batch_start,
            )

            if (
                cycle_index
                % max(
                    1,
                    round(
                        self.config.system.control_rate_hz
                    ),
                )
                == 0
            ):
                self._print_status(
                    elapsed,
                    decision.phase,
                    states_after,
                    targets,
                    command_results,
                )

            if fatal_errors:
                raise RuntimeError("; ".join(fatal_errors))

            cycle_index += 1
            next_tick += period_s
            sleep_s = next_tick - time.monotonic()
            if sleep_s > 0:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=sleep_s,
                    )
                except asyncio.TimeoutError:
                    pass
            else:
                next_tick = time.monotonic()

    def _validate_policy_output(
        self,
        targets: Any,
        states: dict[str, GimbalSnapshot],
    ) -> dict[str, AETarget]:
        if not hasattr(targets, "get"):
            raise TypeError(
                "PolicyDecision.targets must be a mapping"
            )
        output: dict[str, AETarget] = {}
        for device_id, state in states.items():
            if not state.connected or not state.initialized:
                continue
            target = targets.get(device_id)
            if target is None:
                target = state.last_target or AETarget(
                    self.devices[
                        device_id
                    ].config.initial_azimuth_deg,
                    self.devices[
                        device_id
                    ].config.initial_elevation_deg,
                    source="manager_hold_fallback",
                )
                self._event(
                    "WARNING",
                    "policy_target_missing",
                    gimbal_id=device_id,
                    message="holding previous target",
                )
            if not isinstance(target, AETarget):
                raise TypeError(
                    f"Policy target for {device_id} must be AETarget"
                )
            if (
                not math.isfinite(target.azimuth_deg)
                or not math.isfinite(
                    target.elevation_deg
                )
            ):
                raise ValueError(
                    f"Policy target for {device_id} "
                    "contains non-finite angles"
                )
            output[device_id] = target
        return output

    def _log_cycle(
        self,
        *,
        elapsed_s: float,
        cycle_index: int,
        policy_phase: str,
        policy_diagnostics: Any,
        targets: dict[str, AETarget],
        command_results: dict[str, CommandResult],
        states: dict[str, GimbalSnapshot],
        batch_start_monotonic: float,
    ) -> None:
        local_ts, utc_ts = _wall_timestamps()
        diagnostics_json = json.dumps(
            policy_diagnostics,
            ensure_ascii=False,
            default=str,
        )
        tolerance = self.config.system.target_tolerance_deg

        for device_id, state in states.items():
            target = targets.get(device_id) or state.last_target
            result = command_results.get(device_id)
            feedback = state.feedback

            az_error = el_error = error_norm = ""
            in_tolerance: bool | str = ""
            if target is not None and feedback is not None:
                az_error_f = wrap_to_180(
                    target.azimuth_deg
                    - feedback.azimuth_deg
                )
                el_error_f = (
                    target.elevation_deg
                    - feedback.elevation_deg
                )
                error_norm_f = math.hypot(
                    az_error_f, el_error_f
                )
                az_error = f"{az_error_f:.6f}"
                el_error = f"{el_error_f:.6f}"
                error_norm = f"{error_norm_f:.6f}"
                in_tolerance = (
                    error_norm_f <= tolerance
                )

            row = {
                "session_id": self.logger.session_id,
                "timestamp_local": local_ts,
                "timestamp_utc": utc_ts,
                "elapsed_s": f"{elapsed_s:.6f}",
                "cycle_index": cycle_index,
                "policy_name": self.policy.name,
                "policy_phase": policy_phase,
                "policy_diagnostics_json": (
                    diagnostics_json
                ),
                "gimbal_id": state.gimbal_id,
                "gimbal_name": state.name,
                "ip": state.ip,
                "connected": state.connected,
                "initialized": state.initialized,
                "initial_target_reached": (
                    state.initial_target_reached
                ),
                "firmware": state.firmware,
                "motion_mode": state.motion_mode,
                "target_frame": (
                    "" if target is None else target.frame
                ),
                "target_azimuth_deg": (
                    ""
                    if target is None
                    else f"{target.azimuth_deg:.6f}"
                ),
                "target_elevation_deg": (
                    ""
                    if target is None
                    else f"{target.elevation_deg:.6f}"
                ),
                "command_yaw_deg": (
                    ""
                    if result is None
                    else f"{result.command_yaw_deg:.6f}"
                ),
                "command_pitch_deg": (
                    ""
                    if result is None
                    else f"{result.command_pitch_deg:.6f}"
                ),
                "control_mode": (
                    ""
                    if result is None
                    else result.control_mode
                ),
                "yaw_error_deg": (
                    ""
                    if result is None
                    or result.yaw_error_deg is None
                    else f"{result.yaw_error_deg:.6f}"
                ),
                "pitch_error_deg": (
                    ""
                    if result is None
                    or result.pitch_error_deg is None
                    else f"{result.pitch_error_deg:.6f}"
                ),
                "command_yaw_speed": (
                    ""
                    if result is None
                    or result.command_yaw_speed is None
                    else result.command_yaw_speed
                ),
                "command_pitch_speed": (
                    ""
                    if result is None
                    or result.command_pitch_speed is None
                    else result.command_pitch_speed
                ),
                "command_was_clamped": (
                    ""
                    if result is None
                    else result.was_clamped
                ),
                "command_sequence": (
                    ""
                    if result is None
                    else result.sequence
                ),
                "command_sent": (
                    ""
                    if result is None
                    else result.sent
                ),
                "command_status": (
                    ""
                    if result is None
                    else result.status
                ),
                "ack_received": (
                    ""
                    if result is None
                    else result.ack_received
                ),
                "fallback_used": (
                    ""
                    if result is None
                    else result.fallback_used
                ),
                "command_start_elapsed_s": (
                    ""
                    if result is None
                    else (
                        f"{result.start_monotonic_s - self._control_start_monotonic:.6f}"
                    )
                ),
                "command_complete_elapsed_s": (
                    ""
                    if result is None
                    else (
                        f"{result.complete_monotonic_s - self._control_start_monotonic:.6f}"
                    )
                ),
                "command_batch_offset_ms": (
                    ""
                    if result is None
                    else (
                        f"{(result.start_monotonic_s - batch_start_monotonic) * 1000.0:.3f}"
                    )
                ),
                "command_latency_ms": (
                    ""
                    if result is None
                    else f"{result.latency_ms:.3f}"
                ),
                "ack_yaw_deg": (
                    ""
                    if result is None
                    or result.ack_yaw_deg is None
                    else result.ack_yaw_deg
                ),
                "ack_pitch_deg": (
                    ""
                    if result is None
                    or result.ack_pitch_deg is None
                    else result.ack_pitch_deg
                ),
                "ack_roll_deg": (
                    ""
                    if result is None
                    or result.ack_roll_deg is None
                    else result.ack_roll_deg
                ),
                "feedback_timestamp_local": (
                    ""
                    if feedback is None
                    else feedback.timestamp_local
                ),
                "feedback_timestamp_utc": (
                    ""
                    if feedback is None
                    else feedback.timestamp_utc
                ),
                "feedback_sequence": (
                    ""
                    if feedback is None
                    else feedback.sequence
                ),
                "feedback_source": (
                    ""
                    if feedback is None
                    else feedback.source
                ),
                "feedback_age_ms": (
                    ""
                    if state.feedback_age_s is None
                    else f"{state.feedback_age_s * 1000.0:.3f}"
                ),
                "feedback_stale": state.feedback_stale,
                "actual_azimuth_deg": (
                    ""
                    if feedback is None
                    else f"{feedback.azimuth_deg:.6f}"
                ),
                "actual_elevation_deg": (
                    ""
                    if feedback is None
                    else f"{feedback.elevation_deg:.6f}"
                ),
                "actual_yaw_deg": (
                    ""
                    if feedback is None
                    else f"{feedback.yaw_deg:.6f}"
                ),
                "actual_pitch_raw_deg": (
                    ""
                    if feedback is None
                    else f"{feedback.pitch_raw_deg:.6f}"
                ),
                "actual_pitch_deg": (
                    ""
                    if feedback is None
                    else f"{feedback.pitch_deg:.6f}"
                ),
                "actual_roll_deg": (
                    ""
                    if feedback is None
                    else f"{feedback.roll_deg:.6f}"
                ),
                "yaw_rate_dps": (
                    ""
                    if feedback is None
                    else f"{feedback.yaw_rate_dps:.6f}"
                ),
                "pitch_rate_dps": (
                    ""
                    if feedback is None
                    else f"{feedback.pitch_rate_dps:.6f}"
                ),
                "roll_rate_dps": (
                    ""
                    if feedback is None
                    else f"{feedback.roll_rate_dps:.6f}"
                ),
                "azimuth_error_deg": az_error,
                "elevation_error_deg": el_error,
                "ae_error_norm_deg": error_norm,
                "in_tolerance": in_tolerance,
                "command_error_count": (
                    state.command_error_count
                ),
                "consecutive_command_errors": (
                    state.consecutive_command_errors
                ),
                "last_error": (
                    result.error
                    if result and result.error
                    else state.last_error
                ),
            }
            self.logger.log_telemetry(row)

    def _print_status(
        self,
        elapsed_s: float,
        phase: str,
        states: dict[str, GimbalSnapshot],
        targets: dict[str, AETarget],
        command_results: dict[str, CommandResult],
    ) -> None:
        parts = [
            f"t={elapsed_s:6.1f}s",
            f"phase={phase}",
        ]
        for device_id, state in states.items():
            target = targets.get(device_id)
            feedback = state.feedback
            if feedback is None:
                parts.append(
                    f"{device_id}: no feedback"
                )
                continue

            target_text = (
                "--"
                if target is None
                else (
                    f"{target.azimuth_deg:+.1f}/"
                    f"{target.elevation_deg:+.1f}"
                )
            )
            result = command_results.get(device_id)
            status = (
                "--"
                if result is None
                else result.status
            )
            speed = ""
            if (
                result is not None
                and result.command_yaw_speed is not None
            ):
                speed = (
                    f", speed="
                    f"{result.command_yaw_speed:+d}/"
                    f"{result.command_pitch_speed:+d}"
                )
            ack = ""
            if result is not None:
                ack = (
                    f", ack={result.ack_received}, "
                    f"fallback={result.fallback_used}"
                )
            note = ""
            if result is not None and result.error:
                note = f", note={result.error}"

            parts.append(
                f"{device_id}: cmd={target_text}, "
                f"actual={feedback.azimuth_deg:+.1f}/"
                f"{feedback.elevation_deg:+.1f}, "
                f"status={status}{speed}{ack}{note}"
            )
        print(" | ".join(parts), flush=True)

    async def _shutdown_all(self) -> None:
        self._event(
            "INFO",
            "shutdown_start",
            message="stopping all gimbals",
        )
        results = await asyncio.gather(
            *(
                device.close()
                for device in self.devices.values()
            ),
            return_exceptions=True,
        )
        for device, result in zip(
            self.devices.values(), results
        ):
            if isinstance(result, Exception):
                self._event(
                    "WARNING",
                    "shutdown_device_failed",
                    gimbal_id=device.id,
                    message=(
                        f"{type(result).__name__}: "
                        f"{result}"
                    ),
                )

    def _event(
        self,
        level: str,
        event: str,
        *,
        gimbal_id: str = "",
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        local_ts, utc_ts = _wall_timestamps()
        elapsed = (
            0.0
            if self._run_start_monotonic == 0.0
            else time.monotonic()
            - self._run_start_monotonic
        )
        self.logger.log_event(
            {
                "session_id": (
                    self.logger.session_id
                ),
                "timestamp_local": local_ts,
                "timestamp_utc": utc_ts,
                "elapsed_s": f"{elapsed:.6f}",
                "level": level,
                "event": event,
                "gimbal_id": gimbal_id,
                "message": message,
                "details_json": json.dumps(
                    details or {},
                    ensure_ascii=False,
                    default=str,
                ),
            }
        )
