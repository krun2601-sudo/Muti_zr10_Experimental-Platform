from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class DeviceConfig:
    id: str
    name: str
    ip: str
    enabled: bool = True
    control_port: int = 37260

    initial_azimuth_deg: float = 0.0
    initial_elevation_deg: float = -10.0

    yaw_min_deg: float = -130.0
    yaw_max_deg: float = 130.0
    pitch_min_deg: float = -85.0
    pitch_max_deg: float = 20.0

    azimuth_to_yaw_sign: float = 1.0
    elevation_to_pitch_sign: float = 1.0

    # SDK velocity-command direction relative to reported angle increase.
    # Keep these separate from coordinate-frame signs above.
    yaw_velocity_sign: float = 1.0
    pitch_velocity_sign: float = 1.0

    yaw_offset_deg: float = 0.0
    pitch_offset_deg: float = 0.0
    normalize_pitch_feedback: bool = True

    command_timeout_s: float = 1.2
    max_retries: int = 1

    control_mode: str = "velocity_p"
    yaw_kp: float = 2.0
    pitch_kp: float = 2.0
    yaw_speed_limit: int = 30
    pitch_speed_limit: int = 30
    minimum_speed: int = 10
    speed_quantization: int = 2
    control_deadband_deg: float = 0.8

    # Reliable movement commands are important for older ZR10 firmware.
    velocity_use_ack: bool = True
    velocity_ack_fallback_nowait: bool = True


@dataclass(slots=True)
class SystemConfig:
    session_name: str = "three_zr10_demo"
    control_rate_hz: float = 10.0
    duration_s: float = 32.0

    attitude_stream_hz: int = 10
    feedback_stale_s: float = 1.0
    fallback_poll_interval_s: float = 0.5
    fresh_feedback_timeout_s: float = 4.0

    connect_attempts: int = 3
    connect_retry_delay_s: float = 1.0
    connect_stagger_s: float = 0.25

    command_wait_for_ack: bool = True
    command_change_threshold_deg: float = 0.05
    command_resend_interval_s: float = 0.30
    target_tolerance_deg: float = 1.5
    max_consecutive_command_errors: int = 5

    require_all_devices: bool = True
    continue_on_command_error: bool = True

    startup_lock_mode: bool = True
    startup_lock_required: bool = False
    startup_center: bool = False
    startup_center_settle_s: float = 3.0
    startup_move_to_initial: bool = True
    startup_initial_required: bool = True
    startup_initial_settle_timeout_s: float = 15.0
    startup_progress_interval_s: float = 1.0

    startup_clear_attitude_stream: bool = True
    startup_stop_motion: bool = True
    startup_connection_settle_s: float = 0.35

    initialization_attempts: int = 2
    initialization_retry_delay_s: float = 1.0

    center_on_shutdown: bool = False
    shutdown_settle_s: float = 0.30
    stop_command_repetitions: int = 2
    stop_command_interval_s: float = 0.08

    log_root: str = "logs"
    csv_queue_size: int = 30000
    csv_flush_interval_s: float = 0.5


@dataclass(slots=True)
class PolicyConfig:
    type: str = "synchronized_steps"
    repeat: bool = False
    steps: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class AppConfig:
    system: SystemConfig
    policy: PolicyConfig
    gimbals: list[DeviceConfig]
    source_path: str = ""

    def enabled_gimbals(self) -> list[DeviceConfig]:
        return [g for g in self.gimbals if g.enabled]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dataclass_from_dict(cls, data: dict[str, Any]):
    allowed = set(cls.__dataclass_fields__.keys())
    unknown = set(data.keys()) - allowed
    if unknown:
        raise ValueError(f"Unknown fields for {cls.__name__}: {sorted(unknown)}")
    return cls(**data)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}

    system = _dataclass_from_dict(SystemConfig, raw.get("system", {}))
    policy = _dataclass_from_dict(PolicyConfig, raw.get("policy", {}))
    gimbals = [_dataclass_from_dict(DeviceConfig, item) for item in raw.get("gimbals", [])]

    config = AppConfig(
        system=system,
        policy=policy,
        gimbals=gimbals,
        source_path=str(config_path),
    )
    _validate_config(config)
    return config


def _validate_config(config: AppConfig) -> None:
    devices = config.enabled_gimbals()
    if not devices:
        raise ValueError("At least one enabled gimbal is required")

    ids = [g.id for g in devices]
    ips = [g.ip for g in devices]
    if len(set(ids)) != len(ids):
        raise ValueError(f"Duplicate gimbal IDs: {ids}")
    if len(set(ips)) != len(ips):
        raise ValueError(f"Duplicate gimbal IPs: {ips}")

    s = config.system
    if s.control_rate_hz <= 0:
        raise ValueError("system.control_rate_hz must be positive")
    if s.attitude_stream_hz not in {2, 4, 5, 10, 20, 50, 100}:
        raise ValueError("attitude_stream_hz must be one of 2, 4, 5, 10, 20, 50, 100")
    if s.connect_attempts < 1 or s.initialization_attempts < 1:
        raise ValueError("connect_attempts and initialization_attempts must be at least 1")
    if min(s.connect_retry_delay_s, s.connect_stagger_s, s.initialization_retry_delay_s) < 0:
        raise ValueError("retry/stagger delays cannot be negative")
    if s.feedback_stale_s <= 0 or s.fresh_feedback_timeout_s <= 0:
        raise ValueError("feedback timeout values must be positive")
    if s.max_consecutive_command_errors < 1:
        raise ValueError("max_consecutive_command_errors must be at least 1")
    if s.stop_command_repetitions < 1:
        raise ValueError("stop_command_repetitions must be at least 1")

    for gimbal in devices:
        if gimbal.yaw_min_deg >= gimbal.yaw_max_deg:
            raise ValueError(f"Invalid yaw limits for {gimbal.id}")
        if gimbal.pitch_min_deg >= gimbal.pitch_max_deg:
            raise ValueError(f"Invalid pitch limits for {gimbal.id}")
        if gimbal.azimuth_to_yaw_sign == 0 or gimbal.elevation_to_pitch_sign == 0:
            raise ValueError(f"Angle signs cannot be zero for {gimbal.id}")
        if gimbal.yaw_velocity_sign not in {-1.0, 1.0}:
            raise ValueError(f"yaw_velocity_sign must be +1 or -1 for {gimbal.id}")
        if gimbal.pitch_velocity_sign not in {-1.0, 1.0}:
            raise ValueError(f"pitch_velocity_sign must be +1 or -1 for {gimbal.id}")
        if gimbal.control_mode not in {"position", "velocity_p"}:
            raise ValueError(f"{gimbal.id}.control_mode must be 'position' or 'velocity_p'")
        if gimbal.yaw_kp <= 0 or gimbal.pitch_kp <= 0:
            raise ValueError(f"P gains must be positive for {gimbal.id}")
        if not 1 <= gimbal.yaw_speed_limit <= 100:
            raise ValueError(f"yaw_speed_limit must be in [1, 100] for {gimbal.id}")
        if not 1 <= gimbal.pitch_speed_limit <= 100:
            raise ValueError(f"pitch_speed_limit must be in [1, 100] for {gimbal.id}")
        if not 0 <= gimbal.minimum_speed <= 100:
            raise ValueError(f"minimum_speed must be in [0, 100] for {gimbal.id}")
        if gimbal.speed_quantization < 1:
            raise ValueError(f"speed_quantization must be at least 1 for {gimbal.id}")
        if gimbal.control_deadband_deg < 0:
            raise ValueError(f"control_deadband_deg cannot be negative for {gimbal.id}")

    if config.policy.type == "synchronized_steps":
        if not config.policy.steps:
            raise ValueError("synchronized_steps policy requires at least one step")
        for index, step in enumerate(config.policy.steps):
            if float(step.get("duration_s", 0.0)) <= 0:
                raise ValueError(f"policy.steps[{index}].duration_s must be positive")
            if "azimuth_deg" not in step or "elevation_deg" not in step:
                raise ValueError(
                    f"policy.steps[{index}] must contain azimuth_deg and elevation_deg"
                )
