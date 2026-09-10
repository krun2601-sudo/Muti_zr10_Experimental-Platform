"""动作空间、能力注册和完整校验：先检查整个动作，再允许设备执行。

把不可调/尚未确认的参数也列入能力表，是为了明确边界而非假装支持。
用户可通过 enabled 列表做消融实验；设备能力与算法可选动作是两层约束。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from .config import LabConfig
from .models import Action, Telemetry


@dataclass(frozen=True)
class ParameterSpec:
    unit: str
    support: str
    description: str


PARAMETERS = {
    "yaw_deg": ParameterSpec("deg", "supported", "校准后本地目标方位"),
    "pitch_deg": ParameterSpec("deg", "supported", "校准后本地目标俯仰"),
    "zoom": ParameterSpec("ratio", "firmware", "绝对倍率；仅允许已标定范围"),
    "focal_length_mm": ParameterSpec("mm", "calibration", "通过实测焦距—倍率表换算"),
    "focus_direction": ParameterSpec("-1/0/1", "firmware", "协议负向/停止/正向，近远需实测，持续动作需要租约"),
    "zoom_direction": ParameterSpec("-1/0/1", "firmware", "缩小/停止/放大，持续动作需要租约"),
    "autofocus": ParameterSpec("bool", "firmware", "对视频中心单次自动对焦"),
    "gimbal_mode": ParameterSpec("enum", "firmware", "lock/follow/fpv"),
    "photo": ParameterSpec("bool", "firmware", "单次拍照，不能按控制频率重复触发"),
    "record_toggle": ParameterSpec("bool", "firmware", "切换设备录像，非幂等，不自动重试"),
    "hdr_toggle": ParameterSpec("bool", "firmware", "切换 HDR，非幂等，不自动重试"),
    "osd": ParameterSpec("bool", "firmware", "OSD 开关"),
    "encoding": ParameterSpec("object", "firmware", "视频编码参数，改变后必须重新核验内参/延迟"),
    "roll_deg": ParameterSpec("deg", "read_only", "读取横滚参与投影；不假设可独立控制"),
    "aperture": ParameterSpec("f_number", "unsupported", "ZR10 自动光圈，当前 SDK 无核实的设置接口"),
    "exposure": ParameterSpec("s", "unsupported", "当前选定 SDK 无核实的手动曝光接口"),
    "white_balance": ParameterSpec("enum", "read_only", "官方规格为自动白平衡"),
    "gain": ParameterSpec("dB", "unsupported", "当前选定 SDK 无核实的手动增益接口"),
}


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"动作参数 {name} 必须是有限数值")
    return float(value)


class ActionValidator:
    def __init__(self, cfg: LabConfig):
        self.cfg = cfg
        self.devices = {d.id: d for d in cfg.active_devices}
        self.enabled = set(cfg.action_space.get("enabled", ["yaw_deg", "pitch_deg"]))
        unknown = self.enabled - PARAMETERS.keys()
        if unknown:
            raise ValueError(f"未知动作维度: {sorted(unknown)}")

    def validate(self, action: Action, state: Telemetry, t: float, dt: float) -> Action:
        if action.device_id not in self.devices or state.device_id != action.device_id:
            raise ValueError("动作设备 ID 与遥测不匹配")
        if not math.isfinite(action.issued_t) or not math.isfinite(action.ttl_s) or action.ttl_s <= 0:
            raise ValueError("动作租约必须为有限正时长")
        if action.issued_t > t + 0.05 or t > action.issued_t + action.ttl_s:
            raise ValueError("动作来自未来或已过期")
        d = self.devices[action.device_id]
        values = dict(action.parameters)
        for key in ("yaw_deg", "pitch_deg", "zoom"):
            value = getattr(action, key)
            if key in values:
                raise ValueError(f"{key} 必须使用 Action 同名字段，不能放入 parameters")
            if value is not None:
                values[key] = value
        for key, value in values.items():
            if key not in PARAMETERS:
                raise ValueError(f"未注册的参数 {key}")
            if key not in self.enabled:
                raise ValueError(f"参数 {key} 已被实验动作掩码冻结")
            spec = PARAMETERS[key]
            if spec.support in ("read_only", "unsupported"):
                raise ValueError(f"参数 {key}: {spec.description}")
            if key not in ("yaw_deg", "pitch_deg", "zoom", "focal_length_mm") and not d.capabilities.get(key, False):
                raise ValueError(f"{d.id} 尚未确认支持 {key}，请核验固件后设置 capabilities")
            if key in ("yaw_deg", "pitch_deg", "zoom"):
                value = _finite(value, key)
                limits = {"yaw_deg": d.yaw_limits_deg, "pitch_deg": d.pitch_limits_deg, "zoom": d.zoom_limits}[key]
                if not limits[0] <= value <= limits[1]:
                    raise ValueError(f"{d.id} {key}={value} 超过限位 {limits}；不静默截断")
                if key == "zoom" and d.capabilities.get("zoom", True) is False:
                    raise ValueError(f"{d.id} 禁用了绝对变焦")
            elif key in ("focus_direction", "zoom_direction"):
                if isinstance(value, bool) or value not in (-1, 0, 1):
                    raise ValueError(f"{key} 仅接受 -1/0/1")
            elif key == "gimbal_mode":
                if value not in ("lock", "follow", "fpv"):
                    raise ValueError("未知云台模式")
            elif key == "encoding":
                if not isinstance(value, dict) or not value:
                    raise ValueError("encoding 必须为非空字典")
                # 详细字段由适配器按锁定 SDK 的 EncodingParams 进一步完整检查。
                if not all(isinstance(k, str) for k in value):
                    raise ValueError("encoding 字段名称必须为字符串")
            elif key == "focal_length_mm":
                _finite(value, key)
            elif type(value) is not bool:
                raise ValueError(f"{key} 需要布尔值")
        if "zoom_direction" in values and (action.zoom is not None or "focal_length_mm" in values):
            raise ValueError("同一动作不能同时使用绝对变焦和连续变焦")
        if "focus_direction" in values and values.get("autofocus"):
            raise ValueError("同一动作不能同时使用手动与自动聚焦")
        if "focal_length_mm" in values:
            self.resolve(action)  # 检查映射能力/标定，但不改变动作；反复validate必须幂等。
        return action

    def resolve(self, action: Action) -> Action:
        """设备/仿真执行前把虚拟参数换成底层参数；先调用 validate。

        策略、日志和中间层始终保留原请求，避免焦距动作经过两次校验后
        被误判为修改了冻结的 zoom 维度。
        """
        if "focal_length_mm" in action.parameters:
            import numpy as np
            d = self.devices[action.device_id]
            if not d.capabilities.get("zoom", True):
                raise ValueError("设备已禁用绝对变焦，不能通过焦距参数绕过")
            table = d.camera.get("focal_length_table", [])
            if len(table) < 2 or action.zoom is not None:
                raise ValueError("焦距控制需要至少两个实测标定点，且不能同时指定倍率")
            mm = [float(row["focal_length_mm"]) for row in table]
            zz = [float(row["zoom"]) for row in table]
            if not all(math.isfinite(v) for v in mm+zz) or zz != sorted(set(zz)):
                raise ValueError("焦距—倍率表必须有限且严格递增")
            if mm != sorted(set(mm)) or not mm[0] <= action.parameters["focal_length_mm"] <= mm[-1]:
                raise ValueError("焦距标定表未递增或请求超出范围")
            zoom = float(np.interp(action.parameters["focal_length_mm"], mm, zz))
            if not d.zoom_limits[0] <= zoom <= d.zoom_limits[1]:
                raise ValueError("焦距换算倍率超出设备限制")
            params = dict(action.parameters)
            params.pop("focal_length_mm")
            action = replace(action, zoom=zoom, parameters=params)
        return action
