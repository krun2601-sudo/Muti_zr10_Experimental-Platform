"""配置读取与启动前检查。配置错误应在连接设备前暴露。"""
from __future__ import annotations

import copy
import ipaddress
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class DeviceConfig:
    id: str
    ip: str = "192.168.144.25"
    port: int = 37260
    position_m: tuple[float, float, float] = (0, 0, 0)
    mount_rpy_deg: tuple[float, float, float] = (0, 0, 0)
    enabled: bool = True
    # 以下限制属于校准后的本地角度空间；SDK 原始符号/偏置见 control。
    yaw_limits_deg: tuple[float, float] = (-130, 130)
    pitch_limits_deg: tuple[float, float] = (-85, 25)
    zoom_limits: tuple[float, float] = (1, 10)
    initial_yaw_deg: float = 0.0
    initial_pitch_deg: float = 15.0
    initial_zoom: float = 1.0
    max_slew_dps: float = 30.0
    camera: dict[str, Any] = field(default_factory=dict)
    control: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    calibration_verified: bool = False
    rtsp_url: str = ""


@dataclass
class LabConfig:
    devices: list[DeviceConfig]
    system: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    fusion: dict[str, Any] = field(default_factory=dict)
    simulation: dict[str, Any] = field(default_factory=dict)
    detector: dict[str, Any] = field(default_factory=dict)
    action_space: dict[str, Any] = field(default_factory=dict)
    logging: dict[str, Any] = field(default_factory=dict)
    # 可选总控制中心设置；留空时保持原有命令行运行方式。
    # 算法本体仍遵守 Policy 接口，界面设置不会混入算法观测数据。
    control_center: dict[str, Any] = field(default_factory=dict)
    source: str = ""

    @property
    def active_devices(self) -> list[DeviceConfig]:
        return [d for d in self.devices if d.enabled]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite_vector(value: Any, n: int, name: str) -> None:
    if len(value) != n or not all(math.isfinite(float(x)) for x in value):
        raise ValueError(f"{name} 需要 {n} 个有限数值")


def validate_config(cfg: LabConfig) -> None:
    ids: set[str] = set()
    ips: set[tuple[str, int]] = set()
    if not cfg.active_devices:
        raise ValueError("至少配置一台启用设备；空间定位模式另行要求至少两台")
    for d in cfg.devices:
        for name in ("enabled", "calibration_verified"):
            if type(getattr(d, name)) is not bool:
                raise ValueError(f"{d.id}: {name} 必须为 true/false 布尔值，不能填写字符串或 ture")
        if not isinstance(d.capabilities, dict) or any(type(value) is not bool for value in d.capabilities.values()):
            raise ValueError(f"{d.id}: capabilities 必须是参数名到 true/false 的映射")
        if not d.id or d.id in ids:
            raise ValueError(f"重复或空设备 ID: {d.id}")
        ids.add(d.id)
        ipaddress.ip_address(d.ip)
        if not 1 <= d.port <= 65535:
            raise ValueError("UDP 端口必须在 1..65535")
        endpoint = (d.ip, d.port)
        if d.enabled and endpoint in ips:
            raise ValueError(f"启用设备地址重复: {endpoint}")
        if d.enabled:
            ips.add(endpoint)
        _finite_vector(d.position_m, 3, "position_m")
        _finite_vector(d.mount_rpy_deg, 3, "mount_rpy_deg")
        for name, limits, initial in [
            ("yaw", d.yaw_limits_deg, d.initial_yaw_deg),
            ("pitch", d.pitch_limits_deg, d.initial_pitch_deg),
            ("zoom", d.zoom_limits, d.initial_zoom),
        ]:
            _finite_vector(limits, 2, name)
            if limits[0] >= limits[1] or not limits[0] <= initial <= limits[1]:
                raise ValueError(f"{d.id}: {name} 限位/初始值不合法")
        if d.zoom_limits[0] < 1 or not math.isfinite(d.max_slew_dps) or d.max_slew_dps <= 0:
            raise ValueError(f"{d.id}: 倍率或角速度不合法")
        for key in ("yaw_sign", "pitch_sign", "yaw_velocity_sign", "pitch_velocity_sign"):
            if d.control.get(key, 1) not in (-1, 1):
                raise ValueError(f"{d.id}: {key} 必须为 +1 或 -1")
        if d.control.get("mode", "velocity_p") not in ("velocity_p", "position"):
            raise ValueError("control.mode 仅支持 velocity_p / position")
        camera = d.camera
        for name,default in (("video_latency_s",0),("time_uncertainty_s",.15),("angular_std_deg",.15)):
            value = float(camera.get(name,default))
            if not math.isfinite(value) or value<0 or (name=="angular_std_deg" and value==0):
                raise ValueError(f"{d.id}: camera.{name} 不合法")
        _finite_vector(camera.get("image_size", [1920, 1080]), 2, "image_size")
        if min(camera.get("image_size", [1920, 1080])) <= 0:
            raise ValueError("图像宽高必须大于 0")
        table = camera.get("intrinsics", [])
        zooms = [float(row["zoom"]) for row in table]
        if zooms != sorted(set(zooms)):
            raise ValueError("内参表 zoom 必须严格递增且不重复")
        for row in table:
            if not all(math.isfinite(float(row[k])) for k in ("zoom", "fx", "fy", "cx", "cy")):
                raise ValueError("内参含非有限数值")
            if min(row["fx"], row["fy"]) <= 0:
                raise ValueError("fx/fy 必须为正")
    for section, name, default in [
        (cfg.system, "rate_hz", 10), (cfg.system, "duration_s", 60),
        (cfg.system, "telemetry_stale_s", 0.5), (cfg.system, "max_frame_age_s", 0.6),
        (cfg.fusion, "max_time_skew_s", 0.08),
    ]:
        value = float(section.get(name, default))
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} 必须为有限正数")
    allowed = cfg.action_space.get("enabled", ["yaw_deg", "pitch_deg"])
    if not isinstance(allowed, list) or len(set(allowed)) != len(allowed):
        raise ValueError("action_space.enabled 必须是不重复的参数列表")
    probability = float(cfg.simulation.get("detection_probability",.96))
    noise = float(cfg.simulation.get("pixel_noise_std",.7))
    if not 0<=probability<=1 or not math.isfinite(noise) or noise<0:
        raise ValueError("检测概率必须在0..1，像素噪声必须有限非负")
    target_ids = set()
    for i,target in enumerate(cfg.simulation.get("targets",[])):
        target_id = str(target.get("id",f"uav_{i+1}"))
        if target_id in target_ids:
            raise ValueError("仿真目标ID不能重复")
        target_ids.add(target_id)
        for key in ("position_m","velocity_mps","amplitude_m"):
            if key in target:
                _finite_vector(target[key],3,key)
        period = float(target.get("period_s",30))
        if not math.isfinite(period) or period<=0:
            raise ValueError("目标运动周期必须为有限正数")
        phase = target.get("phase_rad",0)
        if isinstance(phase,(list,tuple)):
            _finite_vector(phase,3,"phase_rad")
        elif not math.isfinite(float(phase)):
            raise ValueError("目标相位必须为有限数值")
    for outage in cfg.simulation.get("outages",[]):
        if outage.get("device_id") not in ids or not all(math.isfinite(float(outage[k])) for k in ("start_s","end_s")) or outage["start_s"]>=outage["end_s"]:
            raise ValueError("掉线场景需要有效设备ID和递增时间区间")
    _validate_control_center(cfg.control_center)
    if cfg.control_center.get("modes"):
        # 列出注册模式不执行插件代码；提前拒绝拼错字段，避免界面运行中
        # 才发现已应用的配置不能生成模式列表。
        from .control_modes import mode_catalog
        mode_catalog(cfg)


def _validate_control_center(options: dict[str, Any]) -> None:
    """界面/通信选项在启动前校验；不允许关闭手动控制的失联保护。"""
    if not isinstance(options, dict):
        raise ValueError("control_center 必须为映射")
    for name in ("enabled", "open_browser", "video_enabled"):
        if name in options and type(options[name]) is not bool:
            raise ValueError(f"control_center.{name} 必须是布尔值")
    bounds = {
        "heartbeat_timeout_s": (1.0, 30.0),
        "preview_fps": (1.0, 15.0),
        "frustum_range_m": (1.0, 10000.0),
        "duration_s": (0.0, 86400.0),
    }
    for name, (minimum, maximum) in bounds.items():
        if name in options:
            value = options[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError(f"control_center.{name} 必须在 {minimum}..{maximum} 内")
    if "port" in options and (type(options["port"]) is not int or not 0 <= options["port"] <= 65535):
        raise ValueError("control_center.port 必须是 0..65535 整数；0 表示自动选择空闲端口")
    if not isinstance(options.get("modes", []), list):
        raise ValueError("control_center.modes 必须是模式列表")


def config_from_dict(data: dict[str, Any]) -> LabConfig:
    raw = copy.deepcopy(data)
    raw.pop("source", None)
    devices = [DeviceConfig(**d) for d in raw.pop("devices", [])]
    cfg = LabConfig(devices=devices, **raw)
    validate_config(cfg)
    return cfg


def _read_with_inheritance(path: Path, seen: set[Path]) -> dict[str, Any]:
    if path in seen:
        raise ValueError("配置 extends 出现循环引用")
    seen.add(path)
    with path.open(encoding="utf-8-sig") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("配置文件顶层必须是映射")
    # 每层资源相对于定义它的 YAML 解析，再合并，继承时保留正确来源目录。
    for name in ("weights", "model_path"):
        if data.get("detector", {}).get(name):
            resource = Path(data["detector"][name])
            if not resource.is_absolute():
                data["detector"][name] = str((path.parent/resource).resolve())
    base = data.pop("extends", None)
    if base:
        parent = _read_with_inheritance((path.parent/base).resolve(),seen)
        def merge(a,b):
            for key,value in b.items():
                if isinstance(value,dict) and isinstance(a.get(key),dict):
                    merge(a[key],value)
                else:
                    a[key] = value
            return a
        data = merge(parent,data)
    return data


def load_config(path: str | Path) -> LabConfig:
    path = Path(path).resolve()
    data = _read_with_inheritance(path,set())
    cfg = config_from_dict(data)
    cfg.source = str(path)
    # 权重/外部资源路径相对于 YAML，而非取决于用户在哪个目录启动。
    for name in ("weights", "model_path"):
        if cfg.detector.get(name):
            p = Path(cfg.detector[name])
            if not p.is_absolute():
                cfg.detector[name] = str((path.parent / p).resolve())
    return cfg
