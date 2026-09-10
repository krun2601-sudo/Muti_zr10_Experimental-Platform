"""总监控中心的会话引擎；HTTP/UI 只通过本模块的公开方法与设备交互。

线程边界是本模块最重要的约定：asyncio 线程独占设备、会话和动作仲裁；
用户策略在单独的 daemon 工作线程计算；CSV 使用原有异步写盘器；视频由
VisionPipeline 独立采集；JPEG 在调用 frame() 的 HTTP 线程编码。
因此慢页面、慢模型、慢策略不会阻止心跳检查和设备软件停机。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import copy
import csv
import math
import queue
import threading
import time
from collections import deque
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .actions import ActionValidator
from .config import config_from_dict
from .models import Action, CommandResult
from .recording import CSVRecorder, dumps, jsonable
from .runtime import Experiment
from .simulation import SimulationWorld


class _AuditLog:
    """会话外操作也保留CSV审计；独立写盘线程避免配置/页面日志阻塞控制。"""
    def __init__(self, root):
        folder = Path(root).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        self.path = folder / f"control_center_audit_{stamp}.csv"
        self.queue = queue.Queue(maxsize=20000)
        self.error = None
        self.thread = threading.Thread(target=self._run, name="center-audit", daemon=True)
        self.thread.start()

    def write(self, kind, payload):
        if self.error:
            raise RuntimeError(f"控制审计日志失败: {self.error}")
        try:
            self.queue.put_nowait((datetime.now(timezone.utc).isoformat(), time.monotonic(), kind, dumps(payload)))
        except queue.Full as exc:
            raise RuntimeError("控制审计日志队列已满") from exc

    def _run(self):
        try:
            with self.path.open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream)
                writer.writerow(["schema_version", "utc", "host_monotonic_s", "kind", "payload_json"])
                while True:
                    item = self.queue.get()
                    if item is None:
                        return
                    writer.writerow([1, *item])
                    if self.queue.empty():
                        stream.flush()
        except Exception as exc:
            self.error = exc

    def close(self):
        if self.thread.is_alive():
            self.queue.put(None, timeout=2)
            self.thread.join(timeout=5)


class _SessionRecorder:
    """关闭后屏蔽已撤销策略线程的迟到写入，不让旧线程污染下一场实验。"""
    def __init__(self, recorder):
        self.recorder = recorder
        self.enabled = True
        self.lock = threading.Lock()

    def write(self, *args, **kwargs):
        with self.lock:
            if self.enabled:
                self.recorder.write(*args, **kwargs)

    def event(self, *args, **kwargs):
        with self.lock:
            if self.enabled:
                self.recorder.event(*args, **kwargs)

    def detach(self):
        with self.lock:
            self.enabled = False


class _PolicyWorker:
    """一场实验一个串行计算线程；不建立无限任务队列。

    Python 无法安全杀死任意用户线程。停止时撤销结果授权，daemon 线程的迟到
    结果被丢弃；这是软件控制边界，不承诺能终止插件自身创建的线程或外部副作用。
    """
    def __init__(self):
        self.queue = queue.Queue(maxsize=1)
        self.closing = threading.Event()
        self.thread = threading.Thread(target=self._run, name="center-policy", daemon=True)
        self.thread.start()

    def _run(self):
        while True:
            item = self.queue.get()
            if item is None:
                return
            future, call = item
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(call())
                except BaseException as exc:
                    future.set_exception(exc)
            if self.closing.is_set():
                return

    async def call(self, function):
        future = concurrent.futures.Future()
        self.queue.put_nowait((future, function))
        return await asyncio.wrap_future(future)

    def close(self):
        self.closing.set()
        with contextlib.suppress(queue.Full):
            self.queue.put_nowait(None)


class ControlCenter:
    """界面无关的总控制中心。构造/start() 本身不连接或转动真实云台。

    使用 command({'action':'start', ...}) 明确开始一次实验。duration_s=0
    表示持续运行。所有运动会话需要浏览器心跳，断开后暂停且不会自动恢复。
    """
    def __init__(self, cfg, *, environment="sim", armed=False, output=None):
        self.cfg = copy.deepcopy(cfg)
        self.environment = self._environment(environment)
        self.armed = bool(armed)
        self.output = output
        self.mode = "manual"
        self.status = "idle"
        self.error = ""
        self.video_enabled = bool(self.options.get("video_enabled", False))
        self.duration_s = float(self.options.get("duration_s", cfg.system.get("duration_s", 60)))
        self.elapsed_s = 0.0
        self._thread = None
        self._loop = None
        self._ready = threading.Event()
        self._lock = threading.RLock()
        self._events = deque(maxlen=200)
        self._event_id = 0
        self._revision = 0
        self._snapshot = {}
        self._last_heartbeat = -math.inf
        self._epoch = 0
        self._session_task = None
        self._fleet = self._vision = self._world = self._experiment = self._recorder = None
        self._session_path = None
        self._states = {}
        self._targets = {}
        self._results = {}
        self._manual = {}
        self._stopped_devices = set()
        self._disconnected = set()
        self._connected_before = {}
        self._tracks = []
        self._detections = []
        self._metrics = {}
        self._diagnostics = {}
        self._histories = {}
        self._history_samples = {}
        self._frames = {}
        self._frame_locks = {}
        self._closed = False
        self._estop_latched = False
        self._audit = None
        self._data_t = 0.
        self._publish()

    @property
    def options(self):
        return getattr(self.cfg, "control_center", {})

    @staticmethod
    def _environment(value):
        if value not in ("sim", "hardware"):
            raise ValueError("environment 只能为 sim 或 hardware")
        return value

    def _catalog(self):
        from .control_modes import mode_catalog
        return mode_catalog(self.cfg)

    def start(self):
        """启动服务线程；幂等，不等于开始实验。"""
        if self._closed:
            raise RuntimeError("控制中心已经关闭")
        if self._thread is None:
            self._audit = _AuditLog(self.output or self.cfg.logging.get("root", "runs"))
            self._thread = threading.Thread(target=self._thread_main, name="control-center", daemon=True)
            self._thread.start()
        if not self._ready.wait(5):
            raise RuntimeError("控制中心线程启动超时")
        return self

    def _thread_main(self):
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._command_lock = asyncio.Lock()
        self._vision_lock = asyncio.Lock()
        ticker = loop.create_task(self._ticker())
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            ticker.cancel()
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    def command(self, payload: dict, timeout=10):
        """线程安全命令桥。返回成功/错误字典，错误不隐式降级或执行部分动作。"""
        if not isinstance(payload, dict):
            return {"ok": False, "error": "命令必须为 JSON 对象"}
        self.start()
        if threading.current_thread() is self._thread:
            raise RuntimeError("command() 不能从控制事件循环线程同步调用")
        future = asyncio.run_coroutine_threadsafe(self._dispatch(copy.deepcopy(payload)), self._loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            return {"ok": False, "error": "操作超时；请检查事件和当前状态，不要假定设备已执行"}

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._snapshot)

    def _event(self, kind, payload=None, t=None):
        payload = jsonable(payload or {})
        t = self._clock() if t is None else t
        # 遥测仍完整进入 telemetry_stream；避免高频原始反馈刷满界面事件。
        if kind != "telemetry":
            if self._audit is not None:
                self._audit.write(kind, payload)
            with self._lock:
                self._event_id += 1
                message = payload.get("error") or payload.get("reason") or payload.get("message") or kind
                self._events.append({"id": self._event_id, "t": t, "kind": kind,
                                     "message": str(message), "payload": payload})
        recorder = self._recorder
        if recorder is not None and not recorder.closed:
            recorder.event(kind, payload, t)

    def _clock(self):
        return self._world.t if self._world is not None else self._data_t if self.environment == "sim" else time.monotonic()

    def _publish(self):
        now = self._clock()
        devices = []
        for d in self.cfg.devices:
            state = self._states.get(d.id)
            feedback = jsonable(state) if state is not None and state.source != "unavailable" else None
            if feedback is not None:
                feedback["age_s"] = max(0, now-state.t)
                # 未读回倍率时不能把配置初值或命令值显示为实测；保留raw供诊断。
                if self.environment == "hardware" and state.raw.get("zoom_known") is not True:
                    feedback["zoom"] = None
                feedback["fresh"] = bool(state.connected)
            devices.append({"id": d.id, "ip": d.ip, "port": d.port, "position_m": d.position_m,
                "mount_rpy_deg": d.mount_rpy_deg, "enabled": d.enabled,
                "connected": bool(state and state.connected and d.id not in self._disconnected),
                "feedback": feedback, "target": jsonable(self._targets.get(d.id)),
                "command": jsonable(self._results.get(d.id)),
                "manual_override": d.id in self._manual or d.id in self._stopped_devices,
                "stopped_by_operator": d.id in self._stopped_devices})
        tracks = []
        for track in self._tracks:
            row = jsonable(track)
            row["history"] = list(self._histories.get(track.track_id, ()))
            # 保留原纯坐标history契约；新界面用带时间/测量标志的采样恢复虚实线。
            row["history_samples"] = list(self._history_samples.get(track.track_id, ()))
            tracks.append(row)
        diagnostics = copy.deepcopy(self._diagnostics)
        if self._vision is not None:
            diagnostics["vision_errors"] = dict(self._vision.errors)
            diagnostics["video_sources"] = {key: source.last_error for key, source in self._vision.sources.items()
                                            if source.last_error}
        diagnostics["heartbeat_age_s"] = max(0, time.monotonic()-self._last_heartbeat)
        with self._lock:
            self._revision += 1
            self._snapshot = jsonable({"revision": self._revision, "t": now,
                "status": "estopped" if self._estop_latched else self.status,
                "environment": self.environment, "mode": self.mode, "elapsed_s": self.elapsed_s,
                "duration_s": self.duration_s, "session_path": self._session_path,
                "audit_path": str(self._audit.path) if self._audit is not None else None, "error": self.error,
                "armed": self.armed, "video_enabled": self.video_enabled, "config": self.cfg.to_dict(),
                "modes": self._catalog(), "devices": devices, "tracks": tracks,
                "detections": self._detections, "metrics": self._metrics,
                "events": list(self._events), "diagnostics": diagnostics})

    async def _ticker(self):
        while True:
            try:
                if self._fleet is not None or self._world is not None:
                    self._states = self._current_states()
                    await self._connection_edges()
                if self.status in ("starting", "running") and not self._heartbeat_live():
                    await self._pause("browser_heartbeat_expired")
                self._publish()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.error = f"监控线程异常: {exc}"
                self.status = "error"
                self._epoch += 1
                await self._revoke("monitor_error")
            await asyncio.sleep(.05)

    def _heartbeat_live(self):
        return time.monotonic()-self._last_heartbeat <= float(self.options.get("heartbeat_timeout_s", 3))

    def _require_heartbeat(self):
        if not self._heartbeat_live():
            raise ValueError("浏览器心跳已断开；重新连接后由操作者明确恢复")

    def _active(self):
        return self._session_task is not None and not self._session_task.done()

    async def _dispatch(self, payload):
        action = payload.get("action")
        try:
            if action == "heartbeat":
                self._last_heartbeat = time.monotonic()
                return {"ok": True, "status": self.status}
            # 急停不能排队等待配置保存、探测或模型加载。
            if action in ("stop", "pause", "estop"):
                if action == "stop":
                    await self._stop_session()
                else:
                    await self._pause("operator_estop" if action == "estop" else "operator_pause",
                                      estop=action == "estop")
                self._publish()
                return {"ok": True, "status": self.status}
            async with self._command_lock:
                result = await self._operation(action, payload)
            self._event("ui_command", {"action": action, "request": payload, "result": result})
            self._publish()
            return {"ok": True, **(result or {})}
        except asyncio.CancelledError:
            # 命令方超时取消时，撤销潜在运动，不让未知结果变成继续运行。
            await self._pause("command_cancelled")
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._event("ui_command_rejected", {"action": action, "request": payload, "error": error})
            self._publish()
            return {"ok": False, "error": error}

    async def _operation(self, action, payload):
        if action == "start":
            if self._estop_latched:
                raise ValueError("软急停已锁存，请先解除，再明确开始/恢复")
            if self._active():
                raise ValueError("当前已有实验会话，请停止后再开始")
            self._require_heartbeat()
            environment = self._environment(payload.get("environment", self.environment))
            armed = payload.get("armed", self.armed)
            if type(armed) is not bool:
                raise ValueError("armed 需要布尔值")
            if environment == "hardware" and not armed:
                raise ValueError("实机会话需要明确启用 armed，probe 可在未启用时只读查询")
            mode = str(payload.get("mode", self.mode))
            self._validate_mode(mode, environment)
            duration = payload.get("duration_s", self.duration_s)
            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0:
                raise ValueError("duration_s 必须是非负有限秒数；0 表示持续运行")
            self.environment, self.armed, self.mode = environment, armed, mode
            self.duration_s, self.elapsed_s, self.error = float(duration), 0., ""
            self._data_t = 0.
            self._epoch += 1
            self._manual.clear(); self._stopped_devices.clear(); self._disconnected.clear()
            self._connected_before.clear()
            self._targets.clear(); self._results.clear(); self._histories.clear(); self._history_samples.clear()
            self._tracks, self._detections, self._metrics, self._diagnostics = [], [], {}, {}
            self.status = "starting"
            self._session_task = asyncio.create_task(self._run_session(), name="center-session")
            return {"status": self.status}
        if action == "reset_estop":
            if not self._estop_latched:
                raise ValueError("当前没有锁存的软急停")
            self._estop_latched = False
            self.status = "paused" if self._active() else "stopped"
            return {"status": self.status, "message": "已解除锁存；尚未恢复运动"}
        if action == "resume":
            if self._estop_latched:
                raise ValueError("请先解除软急停锁存")
            if self.status != "paused" or not self._active():
                raise ValueError("只有仍有会话的暂停状态可以恢复")
            self._require_heartbeat()
            self._validate_mode(self.mode, self.environment)
            self._epoch += 1
            self.status = "running"
            return {"status": self.status}
        if action in ("mode", "reload_policy"):
            if self._active() and self._experiment is None:
                raise ValueError("会话正在初始化算法，请等待启动完成或先停止，再切换模式")
            mode = str(payload.get("mode", self.mode))
            self._validate_mode(mode, self.environment)
            # 先暂停和停机，加载完成后仍保持暂停，需要操作者明确恢复。
            if self._active():
                await self._pause("mode_change" if action == "mode" else "reload_policy")
            from .control_modes import create_mode_policy
            loader = _PolicyWorker()
            try:
                policy = await loader.call(lambda: create_mode_policy(self.cfg, mode, action == "reload_policy"))
            finally:
                loader.close()
            old_mode = self.mode
            self.mode = mode
            try:
                if self._active():
                    await self._ensure_vision()
            except BaseException:
                # 新检测器/模型不可用时保留旧算法，保持暂停；不留下半切换模式。
                self.mode = old_mode
                raise
            if self._experiment is not None:
                self._experiment.policy = policy
            return {"mode": mode, "status": self.status, "message": "算法已加载；恢复后使用新算法"}
        if action in ("manual", "initialize"):
            self._require_motion()
            key = self._device_key(payload)
            values = {name: payload[name] for name in ("yaw_deg", "pitch_deg", "zoom", "parameters") if name in payload}
            skipped = []
            if action == "initialize":
                d = next(d for d in self.cfg.active_devices if d.id == key)
                enabled = set(self.cfg.action_space.get("enabled", ["yaw_deg", "pitch_deg"]))
                values = {}
                for name, initial in (("yaw_deg", d.initial_yaw_deg), ("pitch_deg", d.initial_pitch_deg), ("zoom", d.initial_zoom)):
                    if name in enabled and (name != "zoom" or d.capabilities.get("zoom") is True):
                        values[name] = initial
                    else:
                        skipped.append(name)
            if not values or all(v is None or v == {} for v in values.values()):
                raise ValueError("没有可执行的目标；检查动作掩码和已确认能力")
            if not isinstance(values.get("parameters", {}), dict):
                raise ValueError("parameters 必须是注册参数的对象")
            if "encoding" in values.get("parameters", {}):
                raise ValueError("控制中心运行期间禁止修改encoding；请停止实验，在外部修改编码后重新校验相机分辨率、内参与视频延迟，再开始实验")
            state = self._current_states().get(key)
            if state is None or not state.connected:
                raise ValueError("设备没有新鲜姿态反馈；不能执行手动动作")
            requested = Action(key, **values, issued_t=self._clock(), ttl_s=.5, reason="operator_"+action)
            validator = ActionValidator(self.cfg)
            validator.validate(requested, state, self._clock(), self._dt)
            if self._fleet is not None:
                # 同时执行硬件层参数详细检查，encoding 等非法字段在发送任何AE前拒绝。
                self._fleet.devices[key]._check_action(requested, time.monotonic())
            if self.environment == "sim" and "encoding" in requested.parameters:
                raise ValueError("几何仿真不模拟视频编码切换")
            self._epoch += 1
            self._stopped_devices.add(key)
            self._manual.pop(key, None)
            await self._stop_one(key, "manual_takeover")
            # 停机ACK等待期间急停/掉线可能发生，不能在其后偷偷重新安装动作。
            self._require_motion()
            self._epoch += 1
            # 停机/ACK等待可能消耗原有0.5秒租约；签发前重新取真实状态和时间。
            state = self._current_states().get(key)
            if state is None or not state.connected:
                raise ValueError("接管停机后姿态反馈已失效，目标未下发")
            requested = replace(requested, issued_t=self._clock())
            validator.validate(requested, state, self._clock(), self._dt)
            if self._fleet is not None:
                self._fleet.devices[key]._check_action(requested, time.monotonic())
            self._stopped_devices.discard(key)
            self._manual[key] = requested
            self._targets[key] = requested
            return {"accepted": jsonable(requested), "skipped": skipped,
                    "message": "目标已进入控制邮箱；实际发送/ACK/到位请查看反馈"}
        if action in ("stop_device", "release_manual", "connect", "disconnect"):
            if not self._active():
                raise ValueError("请先开始手动或其他模式的实验会话")
            key = self._device_key(payload)
            self._epoch += 1
            self._manual.pop(key, None)
            self._targets.pop(key, None)
            self._stopped_devices.add(key)
            if action == "stop_device":
                self._stopped_devices.add(key)
                await self._stop_one(key, "operator_stop_device")
            elif action == "release_manual":
                await self._stop_one(key, "release_manual")
                self._stopped_devices.discard(key)
            elif action == "disconnect":
                self._disconnected.add(key)
                self._stopped_devices.add(key)
                await self._stop_one(key, "operator_disconnect")
                if self._fleet is not None:
                    await self._fleet.devices[key].close()
            else:
                self._disconnected.discard(key)
                # 重连后仍保持单台停机，需release或新的manual避免隐式恢复运动。
                self._stopped_devices.add(key)
                if self._fleet is not None:
                    self._fleet.devices[key].start()
            return {"device_id": key, "status": action}
        if action == "video":
            if type(payload.get("enabled")) is not bool:
                raise ValueError("enabled 需要布尔值")
            previous = self.video_enabled
            self.video_enabled = payload["enabled"]
            self._frames.clear()
            try:
                if self._active():
                    await self._ensure_vision()
            except BaseException:
                self.video_enabled = previous
                raise
            return {"enabled": self.video_enabled, "message": "关闭显示不会停止跟踪所需的视频采集"}
        if action == "config":
            if self._active():
                raise ValueError("配置只能在停止状态修改；请先停止实验")
            cfg = config_from_dict(payload["config"])
            cfg.source = self.cfg.source
            from .control_modes import mode_catalog
            # 整份配置先校验成功才提交；错误插件注册不得污染仍可使用的旧配置。
            catalog = mode_catalog(cfg)
            ActionValidator(cfg)
            base = Path(cfg.source).parent if cfg.source else Path.cwd()
            for name in ("weights", "model_path"):
                if cfg.detector.get(name):
                    resource = Path(cfg.detector[name])
                    if not resource.is_absolute():
                        cfg.detector[name] = str((base/resource).resolve())
            self.cfg = cfg
            if self.mode not in {item["id"] for item in catalog}:
                self.mode = "manual"
            self._states = {}; self._targets = {}; self._results = {}
            # 空间结果与生成它们的标定配置绑定；应用新坐标/内参后不能把上一场
            # 轨迹叠到新场景里。历史实验仍完整保存在session_path对应的CSV中。
            self._tracks, self._detections, self._metrics, self._diagnostics = [], [], {}, {}
            self._histories.clear(); self._history_samples.clear(); self._frames.clear()
            self._manual.clear(); self._stopped_devices.clear(); self._disconnected.clear()
            self._connected_before.clear()
            return {"config": self.cfg.to_dict()}
        if action == "save_config":
            if self._active():
                raise ValueError("请停止实验后再保存配置")
            import yaml
            default = Path(self.cfg.source).parent / "control_center_saved.yaml" if self.cfg.source else Path("configs/control_center_saved.yaml")
            path = Path(payload.get("path") or default).resolve()
            if path.suffix.lower() not in (".yaml", ".yml"):
                raise ValueError("配置保存路径必须为 .yaml 或 .yml")
            document = self.cfg.to_dict()
            document.pop("source", None)
            text = yaml.safe_dump(jsonable(document), allow_unicode=True, sort_keys=False)
            def save():
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(path.suffix+".tmp")
                temporary.write_text(text, encoding="utf-8")
                temporary.replace(path)
            await asyncio.to_thread(save)
            return {"path": str(path)}
        if action == "probe":
            if self._active():
                raise ValueError("probe 仅在停止状态可用，避免创建第二套设备连接")
            from .hardware import probe_devices
            return {"results": await probe_devices(self.cfg)}
        raise ValueError(f"未知操作: {action}")

    @property
    def _dt(self):
        return 1/float(self.cfg.system.get("rate_hz", 10))

    def _device_key(self, payload):
        key = payload.get("device_id")
        if key not in {d.id for d in self.cfg.active_devices}:
            raise ValueError("device_id 不存在或未启用")
        return key

    def _require_motion(self):
        self._require_heartbeat()
        if self.status != "running" or self._estop_latched:
            raise ValueError("当前不是运行状态，请开始/恢复会话后再控制")
        if self.environment == "hardware" and not self.armed:
            raise ValueError("实机尚未启用 armed")

    def _validate_mode(self, mode, environment):
        entry = next((item for item in self._catalog() if item["id"] == mode), None)
        if entry is None:
            raise ValueError(f"未注册模式: {mode}")
        if mode in ("scan", "localize", "center", "multi") and len(self.cfg.active_devices) < 2:
            raise ValueError("此协同模式需要至少两台启用设备")
        if environment == "hardware" and entry.get("requires_calibration", mode in ("scan", "localize", "center", "multi")):
            missing = [d.id for d in self.cfg.active_devices if not d.calibration_verified]
            if missing:
                raise ValueError(f"空间观测模式要求实测标定，未完成站点: {missing}")

    def _detection_required(self):
        entry = next(item for item in self._catalog() if item["id"] == self.mode)
        return bool(entry.get("requires_detection", self.mode in ("track", "center", "multi")))

    async def _ensure_vision(self):
        async with self._vision_lock:
            await self._update_vision()

    async def _update_vision(self):
        if self.environment != "hardware":
            return
        if self.status in ("stopped", "idle", "error"):
            return
        required = self._detection_required()
        if not (required or self.video_enabled):
            if self._vision is not None:
                vision, self._vision = self._vision, None
                await vision.close()
            return
        if self._vision is None:
            from .vision import VisionPipeline
            vision = VisionPipeline(self.cfg, event_sink=self._event, detection_enabled=required)
            self._vision = vision
            try:
                await vision.start()
            except BaseException:
                self._vision = None
                await vision.close()
                raise
            if self.status in ("stopped", "idle", "error"):
                self._vision = None
                await vision.close()
        else:
            await self._vision.set_detection_enabled(required)

    def _current_states(self):
        states = self._fleet.states() if self._fleet is not None else self._world.states() if self._world is not None else {}
        return {key: replace(s, connected=False) if key in self._disconnected else s for key, s in states.items()}

    async def _connection_edges(self):
        """一旦观测到反馈失联，撤销该台目标；自动重连不得重放手动动作。"""
        lost = [key for key, state in self._states.items()
                if self._connected_before.get(key, False) and not state.connected]
        self._connected_before = {key: state.connected for key, state in self._states.items()}
        if lost:
            self._epoch += 1
            for key in lost:
                self._manual.pop(key, None)
                self._targets.pop(key, None)
                self._stopped_devices.add(key)
            await asyncio.gather(*(self._stop_one(key, "telemetry_lost") for key in lost))
            self._event("devices_inhibited_after_disconnect", {"device_ids": lost,
                "message": "反馈失联后旧命令已撤销；重连仍保持停机，请释放接管或重新手动控制"})

    def _result(self, result):
        self._results[result.device_id] = result
        original = self._manual.get(result.device_id)
        if original is not None and original.parameters and original.issued_t == result.action.issued_t:
            self._manual[result.device_id] = replace(original, parameters={
                key: value for key, value in original.parameters.items() if key == "focal_length_mm"})
        r = self._recorder
        if r is not None and not r.closed:
            r.write("commands", result.t, device_id=result.device_id, command_t=result.t, status=result.status,
                    sent=result.sent, ack=result.ack, latency_ms=result.latency_ms,
                    applied_json=dumps(result.applied), error=result.error, action_json=dumps(result.action))

    def _telemetry(self, state):
        r = self._recorder
        if r is not None and not r.closed:
            r.write("telemetry_stream", state.t, device_id=state.device_id, sample_t=state.t,
                yaw_deg=state.yaw_deg, pitch_deg=state.pitch_deg, roll_deg=state.roll_deg, zoom=state.zoom,
                yaw_rate_dps=state.yaw_rate_dps, pitch_rate_dps=state.pitch_rate_dps, connected=state.connected,
                sequence=state.sequence, source=state.source, age_s=0, raw_json=dumps(state.raw))

    async def _run_session(self):
        recorder = gate = worker = None
        completed = False
        try:
            from .control_modes import create_mode_policy
            if self.environment == "sim":
                self._world = SimulationWorld(self.cfg)
            recorder = CSVRecorder(self.output or self.cfg.logging.get("root", "runs"), self.cfg.to_dict(),
                                   self.environment, 0. if self.environment == "sim" else time.monotonic())
            self._recorder = recorder
            self._session_path = str(recorder.path)
            gate = _SessionRecorder(recorder)
            worker = _PolicyWorker()
            # 同一个控制中心可连续运行多场实验。每场都刷新入口源文件，避免用户
            # 停止后修改算法、再次开始时仍复用上一场Python模块/pyc缓存。
            self._experiment = await worker.call(lambda: Experiment(
                self.cfg, gate, policy=create_mode_policy(self.cfg, self.mode, reload=True)))
            if self.environment == "hardware":
                from .hardware import HardwareFleet
                self._fleet = HardwareFleet(self.cfg, event_sink=self._event,
                                            result_sink=self._result, telemetry_sink=self._telemetry)
                await self._fleet.start()
                await self._ensure_vision()
            self._states = self._current_states()
            if self.status == "starting":
                self.status = "running"
            self._event("session_started", {"environment": self.environment, "mode": self.mode})
            previous = time.monotonic()
            while True:
                begin = time.monotonic()
                if self.status != "running":
                    previous = begin
                    await asyncio.sleep(.05)
                    continue
                self.elapsed_s += begin-previous
                previous = begin
                if self.duration_s and self.elapsed_s >= self.duration_s:
                    completed = True
                    self.status = "stopped"
                    break
                epoch = self._epoch
                states = self._current_states()
                self._states = states
                t = self._clock()
                detections = self._world.observe() if self._world is not None else self._vision.collect() if self._vision is not None else []
                detections = [d for d in detections if d.device_id not in self._disconnected]
                if not self._detection_required():
                    detections = []
                histories = {d.id: self._fleet.history(d.id) for d in self.cfg.active_devices} if self._fleet is not None else None
                truth = self._world.truth() if self._world is not None else None
                manual = dict(self._manual)
                for key, original in list(manual.items()):
                    if set(original.parameters)-{"focal_length_mm"} and t >= original.issued_t+original.ttl_s:
                        manual[key] = self._manual[key] = replace(original, parameters={
                            name: value for name, value in original.parameters.items() if name == "focal_length_mm"})
                        self._event("manual_parameter_unconfirmed", {"device_id": key,
                            "message": "参数租约已到期，不自动重试；持续AE目标保留"})
                stopped = self._stopped_devices | self._disconnected
                def arbitrate(actions):
                    if epoch != self._epoch or self.status != "running":
                        return {}
                    if any("encoding" in action.parameters for action in actions.values()):
                        raise ValueError("控制中心运行期间禁止修改encoding；请停止实验，在外部修改编码后重新校验相机分辨率、内参与视频延迟，再开始实验")
                    selected = {key: a for key, a in actions.items() if key not in stopped and key not in manual}
                    selected.update({key: (a if set(a.parameters)-{"focal_length_mm"} else replace(a, issued_t=t)) for key, a in manual.items()
                                     if key not in stopped and states[key].connected})
                    return selected
                experiment = self._experiment
                fusion_ids = {d.id for d in self.cfg.active_devices if d.calibration_verified} if self.environment == "hardware" else None
                actions = await worker.call(lambda: experiment.process(t, self._dt, states, detections,
                                            histories.get if histories else None, truth, arbitrate,
                                            fusion_device_ids=fusion_ids,
                                            coverage_enabled=fusion_ids is None or len(fusion_ids) == len(self.cfg.active_devices)))
                # 停止/切换期间的迟到结果没有发送资格，即使策略忽略了暂停状态。
                if epoch != self._epoch or self.status != "running":
                    continue
                self._tracks = experiment.latest["tracks"]
                self._detections = detections
                self._metrics = experiment.latest["metrics"]
                self._diagnostics = experiment.latest["diagnostics"]
                self._remember_tracks()
                self._targets.update(actions)
                if self._fleet is not None:
                    self._fleet.submit(actions)
                else:
                    self._world.advance(actions, self._dt)
                    for a in actions.values():
                        self._result(CommandResult(a.device_id, t, a, "simulated", sent=False, ack=False,
                                                   applied={"simulation": True}))
                # 参数保持原始token和租约，直到硬件返回执行结果；不能按tick换token，
                # 也不能在慢控制器尚未取走邮箱时覆盖它。未知/超时结果不自动重试。
                for key, original in manual.items():
                    if key in actions and self._manual.get(key) is original:
                        if original.parameters:
                            result = self._results.get(key)
                            replied = result is not None and result.action.issued_t == original.issued_t
                            expired = self._clock() >= original.issued_t+original.ttl_s
                            if self._world is not None or replied or expired:
                                self._manual[key] = replace(original, parameters={
                                    name: value for name, value in original.parameters.items() if name == "focal_length_mm"})
                                if expired and not replied and self._fleet is not None:
                                    self._event("manual_parameter_unconfirmed", {"device_id": key,
                                        "message": "参数动作租约已到期且无执行结果，不自动重试"})
                recorder.check()
                delay = self._dt-(time.monotonic()-begin)
                if delay < 0:
                    self._event("deadline_overrun", {"late_s": -delay})
                await asyncio.sleep(max(.001, delay))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.status = "error"
            with contextlib.suppress(Exception):
                self._event("session_error", {"error": self.error})
        finally:
            self._epoch += 1
            if self._vision is not None:
                request = getattr(self._vision, "request_stop", None)
                if request:
                    request()
            self._manual.clear(); self._stopped_devices.clear(); self._targets.clear()
            await self._revoke("session_end")
            if gate is not None:
                gate.detach()
            if worker is not None:
                worker.close()
            fleet = self._fleet
            errors = await asyncio.gather(*(obj.close() for obj in (fleet,) if obj is not None), return_exceptions=True)
            async with self._vision_lock:
                vision, self._vision = self._vision, None
                if vision is not None:
                    try:
                        await vision.close()
                    except Exception as exc:
                        errors.append(exc)
            for error in errors:
                if isinstance(error, BaseException):
                    completed = False
                    self.error = str(error)
                    self.status = "error"
            self._fleet = self._vision = None
            self._data_t = self._clock()
            self._states = {key: replace(state, connected=False) for key, state in self._states.items()}
            if recorder is not None:
                with contextlib.suppress(Exception):
                    self._event("session_stopped", {"completed": completed, "error": self.error})
                try:
                    await asyncio.to_thread(recorder.close, completed)
                except Exception as exc:
                    self.error, self.status = f"CSV关闭失败: {exc}", "error"
            self._recorder = self._experiment = self._world = None
            self._publish()

    def _remember_tracks(self):
        """保存同一批轨迹的两种兼容历史，最多300点，并移除已经删除的轨迹。

        measured来自融合器的真实测量更新标志；轨迹估计连续不代表每个点都有
        新的双站定位。页面重连后可据此恢复预测段的虚线，不把它们冒充实测。
        """
        for track in self._tracks:
            position = list(track.position)
            self._histories.setdefault(track.track_id, deque(maxlen=300)).append(position)
            self._history_samples.setdefault(track.track_id, deque(maxlen=300)).append({
                "t": track.t, "position_m": position, "measured": bool(track.measured)})
        active_ids = {track.track_id for track in self._tracks}
        self._histories = {key: history for key, history in self._histories.items() if key in active_ids}
        self._history_samples = {key: history for key, history in self._history_samples.items() if key in active_ids}

    async def _stop_one(self, key, reason):
        if self._world is not None:
            self._world._actions.pop(key, None)
        if self._fleet is not None:
            await self._fleet.devices[key].cancel_pending(reason)

    async def _revoke(self, reason):
        self._manual.clear(); self._targets.clear()
        if self._world is not None:
            self._world._actions.clear()
        if self._fleet is not None:
            results = await asyncio.gather(*(d.cancel_pending(reason) for d in self._fleet.devices.values()), return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    self.error = f"停机调用失败: {result}"

    async def _pause(self, reason, estop=False):
        self._epoch += 1
        if estop:
            self._estop_latched = True
            self.status = "estopped"
        elif self.status != "estopped" and self._active():
            self.status = "paused"
        await self._revoke(reason)
        if self._fleet is not None or self._world is not None:
            self._states = self._current_states()
        self._event("estop" if estop else "paused", {"reason": reason,
                    "message": "控制指令已撤销；停机送达状态以设备反馈和events为准"})

    async def _stop_session(self):
        was_estopped = self._estop_latched
        self._epoch += 1
        self.status = "estopped" if was_estopped else "stopped"
        if self._vision is not None:
            request = getattr(self._vision, "request_stop", None)
            if request:
                request()
        await self._revoke("operator_stop")
        task = self._session_task
        if task is not None and not task.done():
            task.cancel()
            await task
        self._event("operator_stop", {"status": self.status})

    def frame(self, device_id):
        """返回限频 JPEG；只在HTTP调用线程编码，不打开第二路RTSP。

        仿真帧由模拟检测画出且永久标注 SIMULATION；它不是设备视频。
        """
        snap = self.snapshot()
        if not snap["video_enabled"] or device_id not in {d["id"] for d in snap["devices"] if d["enabled"]}:
            return None
        with self._lock:
            lock = self._frame_locks.setdefault(device_id, threading.Lock())
        with lock:
            now = time.monotonic()
            cached = self._frames.get(device_id)
            if cached and now-cached[0] < 1/float(self.options.get("preview_fps", 6)):
                return cached[1]
            import cv2
            import numpy as np
            if snap["environment"] == "sim":
                image = np.full((360, 640, 3), (35, 26, 20), dtype=np.uint8)
                cv2.line(image, (320, 0), (320, 360), (80, 90, 90), 1)
                cv2.line(image, (0, 180), (640, 180), (80, 90, 90), 1)
                cv2.putText(image, f"SIMULATION  {device_id}", (15, 28), cv2.FONT_HERSHEY_SIMPLEX, .65, (70, 210, 250), 2)
                for d in snap["detections"]:
                    if d["device_id"] == device_id:
                        w, h = d["image_size"]
                        x1,y1,x2,y2 = d["bbox_xyxy"]
                        center = (int((x1+x2)/2*640/w), int((y1+y2)/2*360/h))
                        cv2.circle(image, center, 7, (90, 240, 100), 2)
                cv2.putText(image, "Synthetic camera view - not a real RTSP stream", (12, 344), cv2.FONT_HERSHEY_SIMPLEX, .42, (190, 190, 190), 1)
            else:
                vision = self._vision
                batch = vision.preview_batch(device_id) if vision is not None else None
                if batch is None:
                    return None
                image = batch.frame.image_bgr.copy()
                for item in batch.detections:
                    x1,y1,x2,y2 = map(int, item.bbox_xyxy)
                    cv2.rectangle(image, (x1,y1), (x2,y2), (80,240,100), 2)
                age = now-batch.frame.receive_monotonic_s
                scale = min(1., 960/image.shape[1])
                if scale < 1:
                    image = cv2.resize(image, None, fx=scale, fy=scale)
                label = f"{device_id}  age={age:.2f}s"+("  STALE" if age > 1 else "")
                cv2.putText(image, label, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, .55, (30, 70, 250) if age > 1 else (70,240,130), 2)
            ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 78])
            if not ok:
                return None
            content = data.tobytes()
            self._frames[device_id] = (now, content)
            return content

    def close(self):
        """关闭HTTP服务时调用：取消控制、尝试停机、刷盘，然后结束后台线程。"""
        if self._closed:
            return
        if self._thread is not None:
            self.command({"action": "stop"}, timeout=25)
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
        if self._audit is not None:
            self._audit.close()
        self._closed = True
