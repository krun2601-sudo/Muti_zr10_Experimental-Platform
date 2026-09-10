"""ZR10 的 asyncio 硬件适配层；导入本模块不会连接或转动任何设备。

每台设备拥有独立的连接监督、遥测和控制协程。算法写入最新动作邮箱即返回；
单台设备等待 ACK、断线或重连，不会让其余设备排队。此处所有网络调用都受
超时约束。软件看门狗不能替代断电急停：网线断开后，主机无法保证停机报文到达。
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import math
import time
from collections import deque
from dataclasses import asdict, replace
from typing import Any, Awaitable, Callable

from .config import DeviceConfig, LabConfig
from .models import Action, CommandResult, Telemetry


EventSink = Callable[[str, dict[str, Any]], None]
ResultSink = Callable[[CommandResult], None]
TelemetrySink = Callable[[Telemetry], None]
FREQUENCIES = {2: 1, 4: 2, 5: 3, 10: 4, 20: 5, 50: 6, 100: 7}
PARAMETER_KEYS = frozenset({"focus_direction", "zoom_direction", "autofocus", "gimbal_mode",
                            "photo", "record_toggle", "hdr_toggle", "osd", "encoding"})


def _sdk() -> tuple[Any, Any]:
    """延迟导入：纯仿真不要求安装 SIYI SDK。"""
    try:
        from siyi_sdk import connect_udp, models
    except ImportError as exc:
        raise RuntimeError("请先按安装文档安装 siyi-sdk-v2；仿真模式无需 SDK") from exc
    return connect_udp, models


def normalize_pitch(pitch: float, enabled: bool) -> float:
    """部分旧固件俯仰会差 180°；只在完成方向标定后显式启用此兼容项。"""
    if enabled and pitch > 90:
        return pitch - 180
    if enabled and pitch < -90:
        return pitch + 180
    return pitch


def proportional_speed(error: float, kp: float, limit: int, minimum: int, deadband: float) -> int:
    """输出协议速度整数，既不是角度也不是 deg/s；真实转速由固件决定。"""
    if abs(error) <= deadband:
        return 0
    speed = max(minimum, abs(round(kp * error)))
    return int(math.copysign(min(limit, speed), error))


class HardwareDevice:
    """单个智能体的硬件端；唯一允许调用运动 SDK 的边界。"""

    def __init__(self, device: DeviceConfig, cfg: LabConfig, *, event_sink: EventSink | None = None,
                 result_sink: ResultSink | None = None, telemetry_sink: TelemetrySink | None = None,
                 connector: Any = None, sdk_models: Any = None) -> None:
        self.device, self.cfg = device, cfg
        self.event_sink, self.result_sink = event_sink, result_sink
        self.telemetry_sink = telemetry_sink
        self.connector, self.sdk_models = connector, sdk_models
        self.client: Any = None
        self.state = Telemetry(device.id, 0.0, device.initial_yaw_deg, device.initial_pitch_deg,
                               zoom=device.initial_zoom, connected=False, source="unavailable",
                               raw={"zoom_known": False})
        self.samples: deque[Telemetry] = deque(maxlen=int(cfg.system.get("telemetry_history_size", 1000)))
        self.latest_action: Action | None = None
        self._supervisor: asyncio.Task | None = None
        self._closing = False
        self._unsubscribe: Any = None
        self._unsubscribe_function: Any = None
        self._stream = False
        self._motion_lock = asyncio.Lock()
        self._stopped = True
        self._focus_active = False
        self._zoom_active = False
        self._focus_deadline = self._zoom_deadline = -math.inf
        self._inflight: asyncio.Task | None = None
        self._inflight_action: Action | None = None
        self._watchdog_cancelled = False
        self._zoom_known = False
        self._zoom_pending_target: float | None = None
        self.last_sink_error = ""
        self._zoom_t = -math.inf
        self._last_zoom_command: float | None = None
        self._last_parameter_token: float | None = None
        self._last_position: tuple[float, float] | None = None
        self._last_motion_t = -math.inf
        self._zoom_poll_t = -math.inf
        self._timeout = float(device.control.get("command_timeout_s", 0.25))
        self._rate = float(device.control.get("rate_hz", cfg.system.get("rate_hz", 10)))
        self._stale = float(cfg.system.get("telemetry_stale_s", 0.5))
        self._validator: Any = None
        if not math.isfinite(self._timeout) or self._timeout <= 0 or not math.isfinite(self._rate) or not 1 <= self._rate <= 100:
            raise ValueError("硬件 command_timeout_s 必须为正数，rate_hz 必须在 1..100")
        for axis in ("yaw", "pitch"):
            limit = device.control.get(f"{axis}_speed_limit", 25)
            gain = device.control.get(f"{axis}_kp", 2.0)
            minimum = device.control.get("minimum_speed", 5)
            if type(limit) is not int or not 1 <= limit <= 100 or type(minimum) is not int or not 0 <= minimum <= limit:
                raise ValueError("协议速度限值必须为 1..100 整数，minimum_speed 需在 0..限值")
            if not math.isfinite(gain) or gain < 0:
                raise ValueError("速度 P 增益必须为非负有限数")
        if not 1 <= int(cfg.system.get("stop_repetitions", 2)) <= 10:
            raise ValueError("stop_repetitions 必须为 1..10")

    def _event(self, kind: str, **payload: Any) -> None:
        if self.event_sink:
            try:
                self.event_sink(kind, {"device_id": self.device.id, "t": time.monotonic(), **payload})
            except Exception as exc:
                # 日志故障由运行器 check() 收敛退出；这里决不能阻止真实停机和关闭。
                self.last_sink_error = f"{type(exc).__name__}: {exc}"

    async def _call(self, awaitable: Awaitable, timeout: float | None = None) -> Any:
        return await asyncio.wait_for(awaitable, self._timeout if timeout is None else timeout)

    def start(self) -> None:
        if self._supervisor is not None:
            return
        if self.connector is None:
            self.connector, self.sdk_models = _sdk()
        from .actions import ActionValidator
        self._validator = ActionValidator(self.cfg)
        self._closing = False
        self._supervisor = asyncio.create_task(self._run(), name=f"hardware-{self.device.id}")

    def submit(self, action: Action) -> None:
        if action.device_id != self.device.id:
            raise ValueError("动作设备 ID 与控制器不一致")
        # 旧策略线程晚返回的动作不能覆盖较新的命令。
        if self.latest_action is None or action.issued_t >= self.latest_action.issued_t:
            self.latest_action = replace(action, parameters=copy.deepcopy(action.parameters),
                                         target_ids=tuple(action.target_ids))

    def snapshot(self) -> Telemetry:
        now = time.monotonic()
        connected = self.client is not None and self.state.connected and now - self.state.t <= self._stale
        zoom_known = self._zoom_known and now - self._zoom_t <= float(self.cfg.system.get("zoom_stale_s", 2.0))
        return replace(self.state, connected=connected, raw={**self.state.raw, "zoom_known": zoom_known,
                       "zoom_stable": not self._zoom_active and self._zoom_pending_target is None,
                       "sink_error": self.last_sink_error})

    def _attitude(self, value: Any, source: str = "stream") -> None:
        control = self.device.control
        pitch_raw = float(value.pitch_deg)
        pitch = normalize_pitch(pitch_raw, bool(control.get("normalize_pitch_feedback", True)))
        yaw = (float(value.yaw_deg) - float(control.get("yaw_offset_deg", 0))) / control.get("yaw_sign", 1)
        pitch = (pitch - float(control.get("pitch_offset_deg", 0))) / control.get("pitch_sign", 1)
        numeric = [yaw, pitch, float(value.roll_deg), float(value.yaw_rate_dps), float(value.pitch_rate_dps)]
        if not all(math.isfinite(x) for x in numeric):
            self._event("invalid_telemetry", reason="nonfinite")
            return
        now = time.monotonic()
        raw = {"yaw_deg": float(value.yaw_deg), "pitch_deg": pitch_raw, "roll_deg": float(value.roll_deg),
               "yaw_rate_dps": float(value.yaw_rate_dps), "pitch_rate_dps": float(value.pitch_rate_dps),
               "roll_rate_dps": float(getattr(value, "roll_rate_dps", 0)),
               "timestamp_kind": "host_receive_estimate", "received_utc_s": time.time(),
               "zoom_known": self._zoom_known and now - self._zoom_t <= float(self.cfg.system.get("zoom_stale_s", 2.0)),
               "zoom_t": self._zoom_t if self._zoom_known else None,
               "zoom_stable": not self._zoom_active and self._zoom_pending_target is None}
        self.state = Telemetry(self.device.id, now, yaw, pitch, float(value.roll_deg), self.state.zoom,
                               float(value.yaw_rate_dps) / control.get("yaw_sign", 1),
                               float(value.pitch_rate_dps) / control.get("pitch_sign", 1),
                               True, self.state.sequence + 1, source, raw)
        self.samples.append(self.state)
        if self.telemetry_sink:
            try:
                # 每个真实姿态包恰好输出一次。决策周期 snapshot 不触发此回调，
                # 使高频原始样本和低频算法快照可以分别完整保存、重新做标定。
                self.telemetry_sink(self.state)
            except Exception as exc:
                self.last_sink_error = f"{type(exc).__name__}: {exc}"
        self._event("telemetry", **asdict(self.state))

    async def _connect(self) -> None:
        self.samples.clear()
        self._zoom_known = False
        self._zoom_pending_target = None
        self._last_position = None
        self._last_zoom_command = None
        self._last_parameter_token = None
        self.latest_action = None  # 重连后的动作必须由策略重新产生，不重放旧动作。
        self.client = await self._call(self.connector(
            self.device.ip, self.device.port, timeout=self._timeout, max_retries=0, auto_reconnect=False,
        ), timeout=max(1.0, self._timeout))
        firmware = await self._call(self.client.get_firmware_version())
        self._event("connected", ip=self.device.ip, firmware=str(firmware))
        await self.safe_stop("connect")
        if self.device.control.get("startup_lock", True):
            await self._call(self.client.capture(self.sdk_models.CaptureFuncType.LOCK_MODE))
            self._event("mode_sent", mode="lock", ack=False)
        self._unsubscribe = self.client.on_attitude(self._attitude)
        if callable(getattr(self.client, "on_function_feedback", None)):
            self._unsubscribe_function = self.client.on_function_feedback(
                lambda value: self._event("function_feedback", value=getattr(value, "name", str(value))))
        try:
            hz = int(self.cfg.system.get("attitude_stream_hz", 10))
            if hz not in FREQUENCIES:
                raise ValueError("attitude_stream_hz 必须为 2,4,5,10,20,50,100")
            await self._call(self.client.request_gimbal_stream(
                self.sdk_models.GimbalDataType.ATTITUDE, self.sdk_models.DataStreamFreq.OFF))
            await self._call(self.client.request_gimbal_stream(
                self.sdk_models.GimbalDataType.ATTITUDE, getattr(self.sdk_models.DataStreamFreq, f"HZ{hz}")))
            self._stream = True
        except Exception as exc:
            self._stream = False
            self._event("stream_poll_fallback", error=str(exc))
        self._attitude(await self._call(self.client.get_gimbal_attitude()), "poll")
        await self._read_zoom()

    async def _read_zoom(self) -> None:
        self._zoom_poll_t = time.monotonic()
        try:
            zoom = float(await self._call(self.client.get_current_zoom()))
            if not math.isfinite(zoom) or zoom <= 0:
                raise ValueError("invalid zoom telemetry")
            self._zoom_known, self._zoom_t = True, time.monotonic()
            if self._zoom_pending_target is not None and abs(zoom - self._zoom_pending_target) <= 0.05:
                self._zoom_pending_target = None
            self.state = replace(self.state, zoom=zoom,
                                 raw={**self.state.raw, "zoom_known": True, "zoom_t": self._zoom_t,
                                      "zoom_stable": not self._zoom_active and self._zoom_pending_target is None})
            self._event("zoom_telemetry", zoom=zoom)
        except Exception as exc:
            # 查询失败不把发送目标当成真实焦距，也不因老固件不支持此查询断开云台。
            self._event("zoom_query_failed", error=str(exc))

    async def _telemetry_loop(self) -> None:
        poll_interval = float(self.cfg.system.get("fallback_poll_interval_s", 0.2))
        while not self._closing:
            age = time.monotonic() - self.state.t
            if not self._stream or age > min(self._stale / 2, poll_interval):
                try:
                    self._attitude(await self._call(self.client.get_gimbal_attitude()), "poll")
                except Exception as exc:
                    self._event("telemetry_poll_failed", error=str(exc))
            if time.monotonic() - self.state.t > float(self.cfg.system.get("reconnect_stale_s", 2.0)):
                raise ConnectionError("遥测连续过期，重建 UDP 会话")
            zoom_interval = min(0.1, self._stale / 3) if self._zoom_active else float(self.cfg.system.get("zoom_poll_s", 1.0))
            if time.monotonic() - self._zoom_poll_t >= zoom_interval:
                await self._read_zoom()
            await asyncio.sleep(min(poll_interval, 0.1))

    def _check_action(self, action: Action, now: float) -> Action:
        if not math.isfinite(action.issued_t) or not math.isfinite(action.ttl_s) or action.ttl_s <= 0:
            raise ValueError("动作时间戳/有效期非法")
        if action.issued_t > now + 0.01 or now >= action.issued_t + action.ttl_s:
            raise ValueError("动作过期或来自未来")
        if not self.snapshot().connected:
            raise ValueError("遥测不新鲜，禁止执行动作")
        # 在发出任何一条指令前，对完整动作做统一校验；额外参数也在此验证。
        self._validator.validate(action, self.state, now, 1 / self._rate)
        validated = self._validator.resolve(action)
        unknown = set(validated.parameters) - PARAMETER_KEYS
        if unknown:
            raise ValueError(f"硬件尚未注册参数：{sorted(unknown)}")
        if "encoding" in validated.parameters:
            value = validated.parameters["encoding"]
            required = {"width", "height", "bitrate_kbps"}
            if not required <= value.keys() or set(value) - required - {"stream", "codec"}:
                raise ValueError("encoding 需要 width,height,bitrate_kbps；可选 stream,codec；当前SDK不能设置fps")
            for key in required:
                if type(value[key]) is not int or not 1 <= value[key] <= 65535:
                    raise ValueError(f"encoding.{key} 需要有效正整数")
            if (value["width"], value["height"]) not in ((1920, 1080), (1280, 720)):
                raise ValueError("当前SDK编码器只接受1920×1080或1280×720")
            if value.get("stream", "MAIN") not in ("MAIN", "SUB", "RECORDING") or value.get("codec", "H264") not in ("H264", "H265"):
                raise ValueError("encoding 的 stream/codec 非法")
        direction = validated.parameters.get("zoom_direction", 0)
        if direction:
            if not self._zoom_known or now - self._zoom_t > self._stale:
                raise ValueError("连续变焦需要新鲜变焦反馈以执行限位")
            lo, hi = self.device.zoom_limits
            if direction < 0 and self.state.zoom <= lo or direction > 0 and self.state.zoom >= hi:
                raise ValueError("连续变焦方向已到达配置限位")
        for name, limits in (("yaw_deg", self.device.yaw_limits_deg),
                             ("pitch_deg", self.device.pitch_limits_deg), ("zoom", self.device.zoom_limits)):
            value = getattr(validated, name)
            if value is not None and (not math.isfinite(value) or not limits[0] <= value <= limits[1]):
                raise ValueError(f"{name} 超出设备限位")
        return validated

    async def _control_loop(self) -> None:
        failures = 0
        while not self._closing:
            begin = time.monotonic()
            action = self.latest_action
            if action is None or begin >= action.issued_t + action.ttl_s or not self.snapshot().connected:
                if not self._stopped or self._focus_active or self._zoom_active or self._zoom_pending_target is not None:
                    await self.safe_stop("watchdog")
            else:
                try:
                    validated = self._check_action(action, begin)
                    self._inflight_action = validated
                    self._inflight = asyncio.create_task(self._execute(validated))
                    await self._inflight
                    failures = 0
                except asyncio.CancelledError:
                    if self._watchdog_cancelled and not self._closing:
                        self._watchdog_cancelled = False
                        self._report(action, "watchdog_interrupted", begin, error="发送等待中动作/遥测过期")
                    else:
                        raise
                except Exception as exc:
                    failures += 1
                    self._report(action, "error", begin, error=str(exc))
                    await self.safe_stop("command_error")
                    if failures >= int(self.cfg.system.get("max_command_errors", 3)):
                        raise ConnectionError("连续控制失败") from exc
                finally:
                    self._inflight = None
                    self._inflight_action = None
            await asyncio.sleep(max(0.001, 1 / self._rate - (time.monotonic() - begin)))

    async def _watchdog_loop(self) -> None:
        """独立检查租约；先取消过期 ACK 等待以释放锁，再发送停机命令。

        SDK 的 asyncio 命令可取消。实际调度精度仍取决于操作系统；因此本平台
        提供软件实时控制和可测延迟，不声称具有硬实时或断网安全认证。
        """
        while not self._closing:
            now = time.monotonic()
            action = self._inflight_action or self.latest_action
            expired = action is None or now >= action.issued_t + action.ttl_s
            stale = not self.snapshot().connected
            lens_expired = (self._focus_active and now >= self._focus_deadline or
                            (self._zoom_active or self._zoom_pending_target is not None) and now >= self._zoom_deadline)
            if expired or stale or lens_expired:
                pending = self._inflight
                if pending is not None and not pending.done():
                    self._watchdog_cancelled = True
                    pending.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await pending
                if not self._stopped or self._focus_active or self._zoom_active or self._zoom_pending_target is not None or pending is not None:
                    await self.safe_stop("independent_watchdog")
            await asyncio.sleep(0.01)

    def _report(self, action: Action, status: str, start: float, *, sent: bool = False,
                ack: bool = False, applied: dict | None = None, error: str = "") -> None:
        if self.result_sink:
            try:
                self.result_sink(CommandResult(self.device.id, time.monotonic(), action, status, sent, ack,
                                              (time.monotonic() - start) * 1000, applied or {}, error))
            except Exception as exc:
                self.last_sink_error = f"{type(exc).__name__}: {exc}"

    async def _execute(self, action: Action) -> None:
        begin = time.monotonic()
        applied: dict[str, Any] = {}
        motion_ack = False
        sent = False
        async with self._motion_lock:
            # 获取锁以后再次检查，避免等待期间过期的指令仍然移动设备。
            if begin >= action.issued_t + action.ttl_s or time.monotonic() >= action.issued_t + action.ttl_s:
                raise ValueError("动作在等待发送时过期")
            control = self.device.control
            yaw = self.state.yaw_deg if action.yaw_deg is None else action.yaw_deg
            pitch = self.state.pitch_deg if action.pitch_deg is None else action.pitch_deg
            if action.yaw_deg is not None or action.pitch_deg is not None:
                raw_yaw = yaw * control.get("yaw_sign", 1) + control.get("yaw_offset_deg", 0)
                raw_pitch = pitch * control.get("pitch_sign", 1) + control.get("pitch_offset_deg", 0)
                use_ack = bool(control.get("use_ack", True))
                mode = control.get("mode", "velocity_p")
                if mode == "velocity_p":
                    speeds = []
                    for name, target, current in (("yaw", yaw, self.state.yaw_deg), ("pitch", pitch, self.state.pitch_deg)):
                        error = (target - current) * control.get(f"{name}_sign", 1)
                        value = proportional_speed(error, float(control.get(f"{name}_kp", 2.0)),
                                                   min(100, int(control.get(f"{name}_speed_limit", 25))),
                                                   int(control.get("minimum_speed", 5)), float(control.get("deadband_deg", 0.5)))
                        speeds.append(int(value * control.get(f"{name}_velocity_sign", 1)))
                    method = self.client.rotate if use_ack else self.client.rotate_nowait
                    # 不把 ACK 超时后的非零速度自动降级为 nowait，避免未知状态继续运动。
                    await self._call(method(yaw=speeds[0], pitch=speeds[1]))
                    applied.update(yaw_speed=speeds[0], pitch_speed=speeds[1])
                    self._stopped = speeds == [0, 0]
                    sent, motion_ack = True, use_ack
                else:
                    target_pair = (raw_yaw, raw_pitch)
                    if target_pair != self._last_position or begin - self._last_motion_t > 0.5:
                        method = self.client.set_attitude if use_ack else self.client.set_attitude_nowait
                        receipt = await self._call(method(raw_yaw, raw_pitch))
                        if use_ack and receipt is not None:
                            applied["receipt_attitude"] = {key: float(getattr(receipt, key)) for key in ("yaw_deg", "pitch_deg", "roll_deg")}
                        self._last_position, self._last_motion_t = target_pair, time.monotonic()
                        self._stopped = False
                        sent, motion_ack = True, use_ack
                applied.update(yaw_deg=yaw, pitch_deg=pitch, raw_yaw_deg=raw_yaw, raw_pitch_deg=raw_pitch)
            elif not self._stopped:
                # None 表示本周期不继续运动，不能让上一条速度无限保持。
                await self._call(self.client.rotate(yaw=0, pitch=0))
                self._stopped = True
                sent, motion_ack = True, True
            if action.zoom is not None:
                self._zoom_deadline = action.issued_t + action.ttl_s
            if action.zoom is not None and action.zoom != self._last_zoom_command:
                self._ensure_live(action)
                self._zoom_pending_target = float(action.zoom)
                self._zoom_known = False
                await self._call(self.client.absolute_zoom(float(action.zoom)))
                self._last_zoom_command = float(action.zoom)
                applied["zoom_requested"] = action.zoom
                sent = True
            if action.parameters and action.issued_t != self._last_parameter_token:
                # 先记 token：即使中途失败，非幂等触发也不能在下一轮隐式重发。
                self._last_parameter_token = action.issued_t
                for name, value in action.parameters.items():
                    self._ensure_live(action)
                    if name in ("autofocus", "photo", "record_toggle", "hdr_toggle") and not value:
                        applied[name] = {"value": False, "status": "not_triggered", "ack": False}
                        continue
                    if name == "focus_direction":
                        self._focus_deadline = action.issued_t + action.ttl_s
                    elif name == "zoom_direction":
                        self._zoom_deadline = action.issued_t + action.ttl_s
                    acknowledged = await self._parameter(name, value)
                    applied[name] = {"value": value, "ack": acknowledged}
                    self._event("parameter_sent", name=name, value=value, ack=acknowledged)
                    sent = True
        self._report(action, "acknowledged" if motion_ack else "sent_unconfirmed" if sent else "held", begin,
                     sent=sent, ack=motion_ack, applied=applied)

    def _ensure_live(self, action: Action) -> None:
        if time.monotonic() >= action.issued_t + action.ttl_s or not self.snapshot().connected:
            raise ValueError("动作在多参数发送期间过期或遥测过期；后续参数未发送")

    async def _parameter(self, name: str, value: Any) -> bool:
        m = self.sdk_models
        if name == "focus_direction":
            self._focus_active = int(value) != 0  # ACK 丢失也必须在退出时尝试停止。
            await self._call(self.client.manual_focus(int(value)))
        elif name == "zoom_direction":
            self._zoom_active = int(value) != 0
            self._last_zoom_command = None
            self._zoom_pending_target = None
            if not self._zoom_active:
                self._zoom_known = False
            await self._call(self.client.manual_zoom(int(value)))
        elif name == "autofocus":
            if value:
                w, h = self.device.camera.get("image_size", [1920, 1080])
                await self._call(self.client.auto_focus(int(w / 2), int(h / 2)))
        elif name in ("photo", "record_toggle", "hdr_toggle", "gimbal_mode"):
            lookup = {"photo": "PHOTO", "record_toggle": "START_RECORD", "hdr_toggle": "HDR_TOGGLE"}
            if name == "gimbal_mode":
                constant = {"lock": "LOCK_MODE", "follow": "FOLLOW_MODE", "fpv": "FPV_MODE"}[value]
            elif value:
                constant = lookup[name]
            else:
                return False
            await self._call(self.client.capture(getattr(m.CaptureFuncType, constant)))
            return False  # SDK capture 是 fire-and-forget。
        elif name == "osd":
            if not await self._call(self.client.set_osd_flag(bool(value))):
                raise RuntimeError("OSD 操作未获成功状态")
        elif name == "encoding":
            params = m.EncodingParams(
                stream_type=m.StreamType[value.get("stream", "MAIN")],
                enc_type=m.VideoEncType[value.get("codec", "H264")],
                resolution_w=int(value["width"]), resolution_h=int(value["height"]),
                bitrate_kbps=int(value["bitrate_kbps"]),
                frame_rate=0,  # 此SDK的set编码帧不携带frame_rate；不能假称能修改FPS。
            )
            if not await self._call(self.client.set_encoding_params(params)):
                raise RuntimeError("编码参数未获成功状态")
        else:
            raise ValueError(f"未注册参数：{name}")
        return True

    async def cancel_pending(self, reason: str = "operator_stop") -> None:
        """撤销邮箱并中断发送中的旧动作，再停机；防止下一控制周期重发旧目标。

        与仅发零速不同，这是上层暂停/急停/手动仲裁应调用的撤销边界。
        独立看门狗仍继续工作，连接及遥测保持在线。
        """
        self.latest_action = None
        inflight = self._inflight
        if inflight is not None and not inflight.done():
            self._watchdog_cancelled = True
            inflight.cancel()
            await asyncio.gather(inflight, return_exceptions=True)
        await self.safe_stop(reason)

    async def safe_stop(self, reason: str = "requested") -> None:
        """重复停机；ACK 超时仍尝试发送零速报文，并明确记录是否收到 ACK。"""
        if self.client is None:
            return
        acknowledged = False
        errors = []
        async with self._motion_lock:
            for _ in range(int(self.cfg.system.get("stop_repetitions", 2))):
                try:
                    await self._call(self.client.rotate(yaw=0, pitch=0))
                    acknowledged = True
                except Exception as exc:
                    errors.append(str(exc))
                    with contextlib.suppress(Exception):
                        await self._call(self.client.rotate_nowait(yaw=0, pitch=0))
            for name, active in (("manual_focus", self._focus_active),
                                 ("manual_zoom", self._zoom_active or self._zoom_pending_target is not None)):
                if active:
                    try:
                        await self._call(getattr(self.client, name)(0))
                        if name == "manual_focus":
                            self._focus_active = False
                        else:
                            self._zoom_active = False
                            self._zoom_known = False
                            self._zoom_pending_target = None
                            self._last_zoom_command = None
                    except Exception as exc:
                        errors.append(f"{name}: {exc}")
            # 若零速 ACK 未收到，保持未确认状态，后续看门狗/断连退出继续尝试。
            self._stopped = acknowledged
        self._event("stop", reason=reason, ack=acknowledged, error="; ".join(errors))

    async def _disconnect(self) -> None:
        if self._unsubscribe is not None:
            with contextlib.suppress(Exception):
                self._unsubscribe()
            self._unsubscribe = None
        if self._unsubscribe_function is not None:
            with contextlib.suppress(Exception):
                self._unsubscribe_function()
            self._unsubscribe_function = None
        if self.client is not None:
            if self._stream:
                with contextlib.suppress(Exception):
                    await self._call(self.client.request_gimbal_stream(
                        self.sdk_models.GimbalDataType.ATTITUDE, self.sdk_models.DataStreamFreq.OFF))
            try:
                await self._call(self.client.close(), timeout=1.0)
            except Exception as exc:
                self._event("transport_close_failed", error=str(exc))
        self.client, self._stream = None, False
        self.state = replace(self.state, connected=False)

    async def _run(self) -> None:
        backoff = float(self.cfg.system.get("reconnect_initial_s", 0.5))
        while not self._closing:
            children: list[asyncio.Task] = []
            try:
                await self._connect()
                backoff = float(self.cfg.system.get("reconnect_initial_s", 0.5))
                children = [asyncio.create_task(self._telemetry_loop()), asyncio.create_task(self._control_loop()),
                            asyncio.create_task(self._watchdog_loop())]
                done, _ = await asyncio.wait(children, return_when=asyncio.FIRST_EXCEPTION)
                for task in done:
                    task.result()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._event("reconnect", error=f"{type(exc).__name__}: {exc}", retry_s=backoff)
            finally:
                for task in children:
                    task.cancel()
                if children:
                    await asyncio.gather(*children, return_exceptions=True)
                # 先取消控制协程，再发停机，避免退出时停机之后又被旧任务发出非零速度。
                await self.safe_stop("disconnect")
                await self._disconnect()
            if not self._closing:
                await asyncio.sleep(backoff)
                backoff = min(10.0, backoff * 2)

    async def close(self) -> None:
        self._closing = True
        self.latest_action = None
        if self._supervisor is not None:
            self._supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._supervisor
            self._supervisor = None
        elif self.client is not None:
            await self.safe_stop("close")
            await self._disconnect()


class HardwareFleet:
    def __init__(self, cfg: LabConfig, event_sink: EventSink | None = None,
                 result_sink: ResultSink | None = None, telemetry_sink: TelemetrySink | None = None) -> None:
        self.cfg = cfg
        self.devices = {device.id: HardwareDevice(device, cfg, event_sink=event_sink,
                                                 result_sink=result_sink, telemetry_sink=telemetry_sink)
                        for device in cfg.active_devices}

    async def start(self) -> None:
        # start 只创建独立任务，主循环通过 states().connected 判定各站何时可用。
        _sdk()  # 依赖缺失当场报错，避免所有后台任务静默失败。
        for device in self.devices.values():
            device.start()

    def submit(self, actions: dict[str, Action]) -> None:
        for key, action in actions.items():
            if key not in self.devices:
                raise ValueError(f"动作包含未知设备：{key}")
            self.devices[key].submit(action)

    def states(self) -> dict[str, Telemetry]:
        return {key: device.snapshot() for key, device in self.devices.items()}

    def history(self, device_id: str) -> tuple[Telemetry, ...]:
        return tuple(self.devices[device_id].samples)

    async def close(self) -> None:
        results = await asyncio.gather(*(device.close() for device in self.devices.values()), return_exceptions=True)
        failures = [str(result) for result in results if isinstance(result, BaseException)]
        if failures:
            raise RuntimeError("部分设备关闭失败：" + "; ".join(failures))


async def probe_devices(cfg: LabConfig) -> list[dict[str, Any]]:
    """只查询固件和姿态；不订阅、不切模式、不发停机或其他运动命令。"""
    connector, _ = _sdk()

    async def probe(device: DeviceConfig) -> dict[str, Any]:
        client = None
        start = time.monotonic()
        result: dict[str, Any] = {"device_id": device.id, "ip": device.ip, "port": device.port}
        try:
            client = await asyncio.wait_for(connector(device.ip, device.port, timeout=0.5, max_retries=0,
                                                       auto_reconnect=False), 1.0)
            firmware = await asyncio.wait_for(client.get_firmware_version(), 0.7)
            attitude = await asyncio.wait_for(client.get_gimbal_attitude(), 0.7)
            result.update(ok=True, firmware=str(firmware), attitude=asdict(attitude))
        except Exception as exc:
            result.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        finally:
            if client is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(client.close(), 1.0)
        result["latency_ms"] = (time.monotonic() - start) * 1000
        return result

    return await asyncio.gather(*(probe(device) for device in cfg.active_devices))
