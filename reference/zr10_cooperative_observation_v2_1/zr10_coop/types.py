from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class AETarget:
    azimuth_deg: float
    elevation_deg: float
    frame: str = "gimbal_local_ae"
    source: str = "policy"


@dataclass(frozen=True, slots=True)
class GimbalFeedback:
    timestamp_local: str
    timestamp_utc: str
    monotonic_s: float
    yaw_deg: float
    pitch_raw_deg: float
    pitch_deg: float
    roll_deg: float
    azimuth_deg: float
    elevation_deg: float
    yaw_rate_dps: float
    pitch_rate_dps: float
    roll_rate_dps: float
    sequence: int
    source: str = "unknown"


@dataclass(frozen=True, slots=True)
class GimbalSnapshot:
    gimbal_id: str
    name: str
    ip: str
    connected: bool
    initialized: bool
    initial_target_reached: bool
    firmware: str
    motion_mode: str
    feedback: GimbalFeedback | None
    feedback_age_s: float | None
    feedback_stale: bool
    last_target: AETarget | None
    last_command_yaw_deg: float | None
    last_command_pitch_deg: float | None
    last_command_yaw_speed: int | None
    last_command_pitch_speed: int | None
    command_sequence: int
    command_error_count: int
    consecutive_command_errors: int
    last_error: str


@dataclass(frozen=True, slots=True)
class PolicyContext:
    elapsed_s: float
    cycle_index: int
    device_states: Mapping[str, GimbalSnapshot]
    observations: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    targets: Mapping[str, AETarget]
    phase: str = ""
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CommandResult:
    gimbal_id: str
    target: AETarget
    command_yaw_deg: float
    command_pitch_deg: float
    was_clamped: bool
    sequence: int
    sent: bool
    status: str
    start_monotonic_s: float
    complete_monotonic_s: float
    latency_ms: float
    control_mode: str = "position"
    yaw_error_deg: float | None = None
    pitch_error_deg: float | None = None
    command_yaw_speed: int | None = None
    command_pitch_speed: int | None = None
    ack_received: bool = False
    fallback_used: bool = False
    ack_yaw_deg: float | None = None
    ack_pitch_deg: float | None = None
    ack_roll_deg: float | None = None
    feedback_age_s: float | None = None
    error: str = ""
