"""模块之间唯一的数据契约：角度为度，位置为米，时间为单调时钟秒。

算法不要直接引用 SDK、OpenCV 或网络连接。所有可见信息均经这些类型传递。
单调时间只在同一进程/同一次会话中比较，UTC 时间由记录器统一附加。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Telemetry:
    device_id: str
    t: float
    yaw_deg: float
    pitch_deg: float
    roll_deg: float = 0.0
    zoom: float = 1.0
    yaw_rate_dps: float = 0.0
    pitch_rate_dps: float = 0.0
    connected: bool = True
    sequence: int = 0
    source: str = "simulation"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Detection:
    """检测框必须已还原到原始视频分辨率，不是模型缩放后的坐标。

    local_id 是本相机本帧标识，不代表跨相机身份。真值 ID 禁止放入此接口。
    t 为曝光时间估计；received_t 用于记录管线延迟，不能混为曝光时刻。
    """
    device_id: str
    frame_id: int
    t: float
    bbox_xyxy: tuple[float, float, float, float]
    confidence: float = 1.0
    class_id: int = 0
    local_id: str = ""
    image_size: tuple[int, int] = (1920, 1080)
    received_t: float | None = None
    time_uncertainty_s: float = 0.0
    embedding: tuple[float, ...] | None = None

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox_xyxy
        return (x1 + x2) / 2, (y1 + y2) / 2

    @property
    def key(self) -> str:
        return f"{self.device_id}:{self.frame_id}:{self.local_id}"


@dataclass(frozen=True)
class Ray:
    device_id: str
    detection_id: str
    t: float
    origin: tuple[float, float, float]
    direction: tuple[float, float, float]
    confidence: float = 1.0
    angular_std_deg: float = 0.15
    class_id: int = 0
    time_uncertainty_s: float = 0.0
    embedding: tuple[float, ...] | None = None


@dataclass(frozen=True)
class Localization:
    t: float
    position: tuple[float, float, float]
    covariance: tuple[tuple[float, ...], ...]
    device_ids: tuple[str, ...]
    detection_ids: tuple[str, ...]
    residual_m: float
    min_angle_deg: float
    condition_number: float
    time_span_s: float
    class_id: int = 0


@dataclass(frozen=True)
class Track:
    track_id: str
    t: float
    position: tuple[float, float, float]
    velocity: tuple[float, float, float]
    covariance: tuple[tuple[float, ...], ...]
    last_seen_t: float
    hits: int
    status: str  # tentative / confirmed / coasting
    device_ids: tuple[str, ...] = ()
    class_id: int = 0
    measured: bool = True


@dataclass(frozen=True)
class Action:
    """本地云台坐标中的目标角；None 表示本周期不修改该参数。

    parameters 承载已注册的相机参数，不允许借此直接调用任意 SDK 方法。
    issued_t + ttl_s 形成动作租约；硬件不能持续执行已过时的速度指令。
    """
    device_id: str
    yaw_deg: float | None = None
    pitch_deg: float | None = None
    zoom: float | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    target_ids: tuple[str, ...] = ()
    reason: str = "hold"
    issued_t: float = 0.0
    ttl_s: float = 0.5


@dataclass(frozen=True)
class PolicyContext:
    t: float
    dt: float
    step: int
    devices: dict[str, Telemetry]
    detections: tuple[Detection, ...] = ()
    rays: tuple[Ray, ...] = ()
    tracks: tuple[Track, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    actions: dict[str, Action]
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CommandResult:
    device_id: str
    t: float
    action: Action
    status: str
    sent: bool = False
    ack: bool = False
    latency_ms: float = 0.0
    applied: dict[str, Any] = field(default_factory=dict)
    error: str = ""
