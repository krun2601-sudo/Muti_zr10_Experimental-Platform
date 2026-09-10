"""可替换的目标检测与最新帧视频输入。

视觉推理不在 asyncio 控制线程中执行。视频解码使用独立进程，避免 RTSP
底层 read() 卡住时拖死整个实验；队列只保留最新一帧。这里的时间都是主机
解码接收时间及其减去标定延迟后的估计值，绝不能解释为硬件曝光同步。
"""
from __future__ import annotations

import importlib
import math
import multiprocessing as mp
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

import numpy as np

from .config import LabConfig
from .models import Detection


@dataclass(frozen=True, slots=True)
class PixelDetection:
    """统一检测输出：原始完整图像坐标中的 xyxy 框；ID 仅限本相机。"""

    bbox_xyxy: tuple[float, float, float, float]
    confidence: float
    class_id: int = 0
    label: str = "drone"
    local_track_id: str | None = None
    embedding: tuple[float, ...] | None = None

    @property
    def center_uv(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox_xyxy
        return (x1 + x2) / 2, (y1 + y2) / 2


@dataclass(frozen=True, slots=True)
class VideoFrame:
    device_id: str
    frame_id: int
    image_bgr: np.ndarray
    receive_monotonic_s: float
    capture_monotonic_s: float
    receive_utc_s: float
    timestamp_kind: str = "host_receive_estimate"


@dataclass(frozen=True, slots=True)
class DetectionBatch:
    """保留推理输入帧时间，不能用推理完成时间给运动目标打时间戳。"""

    frame: VideoFrame
    detections: tuple[PixelDetection, ...]
    inference_started_s: float
    inference_completed_s: float


class Detector(Protocol):
    def detect(self, image_bgr: np.ndarray) -> list[PixelDetection]:
        """同步推理，由后台工作线程调用；输出必须对应输入原图坐标。"""
        ...


def validate_detections(items: Any, width: int, height: int) -> list[PixelDetection]:
    """所有插件共用边界检验；插件自身仍须保证坐标单位是原图像素。"""
    result = []
    for item in items:
        if isinstance(item, Mapping):
            item = PixelDetection(**item)
        if not isinstance(item, PixelDetection):
            raise TypeError("检测器必须返回 PixelDetection 或具有相同字段的字典")
        x1, y1, x2, y2 = map(float, item.bbox_xyxy)
        if not all(math.isfinite(v) for v in (x1, y1, x2, y2, item.confidence)):
            raise ValueError("检测输出含非有限值")
        if not 0 <= item.confidence <= 1 or x2 <= x1 or y2 <= y1:
            raise ValueError("检测框面积或置信度非法")
        x1, x2 = np.clip([x1, x2], 0, width - 1)
        y1, y2 = np.clip([y1, y2], 0, height - 1)
        if x2 > x1 and y2 > y1:
            result.append(PixelDetection(
                (float(x1), float(y1), float(x2), float(y2)), float(item.confidence),
                int(item.class_id), str(item.label), item.local_track_id, item.embedding,
            ))
    return result


def _option(config: Mapping[str, Any], name: str, alias: str, default: Any) -> Any:
    if name in config and alias in config and config[name] != config[alias]:
        raise ValueError(f"检测器配置 {name} 与别名 {alias} 冲突，请只保留一个")
    return config.get(name, config.get(alias, default))


class UltralyticsDetector:
    """接入用户自己的 YOLO 权重。模型缺失时直接报错，不自动下载替代模型。"""

    def __init__(self, config: Mapping[str, Any]) -> None:
        model_path = Path(str(_option(config, "model_path", "weights", "")))
        if not model_path.is_file():
            raise FileNotFoundError(f"请配置自己的 YOLO 权重文件：{model_path}")
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("YOLO 接入需要 pip install ultralytics") from exc
        self.model = YOLO(str(model_path), task="detect")
        self.confidence = float(config.get("confidence", 0.35))
        self.iou = float(config.get("iou", 0.5))
        self.image_size = int(_option(config, "image_size", "imgsz", 640))
        self.device = config.get("device", "cpu")
        self.classes = config.get("classes")

    def detect(self, image_bgr: np.ndarray) -> list[PixelDetection]:
        prediction = self.model.predict(
            source=image_bgr, conf=self.confidence, iou=self.iou, imgsz=self.image_size,
            device=self.device, classes=self.classes, verbose=False,
        )[0]
        if prediction.boxes is None:
            return []
        boxes = prediction.boxes.xyxy.detach().cpu().numpy()
        scores = prediction.boxes.conf.detach().cpu().numpy()
        classes = prediction.boxes.cls.detach().cpu().numpy().astype(int)
        return [PixelDetection(tuple(map(float, box)), float(score), int(cls),
                               str(prediction.names[int(cls)]))
                for box, score, cls in zip(boxes, scores, classes)]


class CustomDetector:
    """module:factory 插件：factory(config) 返回具有 detect(image_bgr) 的对象。"""

    def __init__(self, config: Mapping[str, Any]) -> None:
        module, separator, symbol = str(config.get("factory", "")).partition(":")
        if not separator:
            raise ValueError("custom 检测器 factory 必须形如 my_detector:create_detector")
        self.implementation = getattr(importlib.import_module(module), symbol)(dict(config))
        if not callable(getattr(self.implementation, "detect", None)):
            raise TypeError("factory 返回的对象缺少 detect(image_bgr) 方法")

    def detect(self, image_bgr: np.ndarray) -> list[PixelDetection]:
        return self.implementation.detect(image_bgr)


def decode_onnx_output(
    output: np.ndarray, *, output_format: str, input_size: tuple[int, int],
    original_size: tuple[int, int], scale: float, pad_xy: tuple[int, int],
    confidence: float, iou: float, classes: list[int] | None = None,
    labels: list[str] | None = None,
) -> list[PixelDetection]:
    """仅支持显式声明的两种 ONNX 输出，绝不按尺寸猜测 YOLO 版本。

    xyxy_score_class：N×6（或 1×N×6），输入 letterbox 像素单位，末列是类别。
    yolov8：1×(4+C)×N（或 (4+C)×N），中心 xywh 加 C 类概率，无 objectness。
    YOLOv5、归一化框、多输出模型请使用 custom 插件解码。
    """
    import cv2
    arr = np.asarray(output, dtype=np.float32)
    if arr.ndim == 3:
        if arr.shape[0] != 1:
            raise ValueError("ONNX 解码仅支持 batch=1")
        arr = arr[0]
    if arr.ndim != 2 or not np.isfinite(arr).all():
        raise ValueError("ONNX 输出必须是有限二维数组或 batch=1 的三维数组")
    if output_format == "xyxy_score_class":
        if arr.shape[1] != 6:
            raise ValueError("xyxy_score_class 输出必须是 N×6")
        boxes, scores, class_values = arr[:, :4], arr[:, 4], arr[:, 5]
        if np.any(class_values != np.round(class_values)) or np.any(class_values < 0):
            raise ValueError("ONNX 类别编号必须为非负整数")
        class_ids = class_values.astype(int)
    elif output_format == "yolov8":
        if arr.shape[0] < 5:
            raise ValueError("yolov8 输出必须是 (4+C)×N")
        rows = arr.T
        class_ids = np.argmax(rows[:, 4:], axis=1)
        scores = rows[np.arange(len(rows)), class_ids + 4]
        boxes = np.empty((len(rows), 4), dtype=np.float32)
        boxes[:, :2] = rows[:, :2] - rows[:, 2:4] / 2
        boxes[:, 2:] = rows[:, :2] + rows[:, 2:4] / 2
    else:
        raise ValueError(f"未支持的 ONNX output_format：{output_format}")
    if np.any((scores < 0) | (scores > 1)):
        raise ValueError("ONNX score 必须为概率；若输出 logits 请写 custom 解码器")
    mask = scores >= confidence
    if classes is not None:
        mask &= np.isin(class_ids, classes)
    boxes, scores, class_ids = boxes[mask], scores[mask], class_ids[mask]
    result = []
    # 按类别 NMS，避免两个不同类别恰好重叠时互相抑制。
    for cls in np.unique(class_ids):
        indices = np.where(class_ids == cls)[0]
        xywh = boxes[indices].copy()
        xywh[:, 2:] -= xywh[:, :2]
        keep = cv2.dnn.NMSBoxes(xywh.tolist(), scores[indices].tolist(), confidence, iou)
        for offset in np.asarray(keep, dtype=int).reshape(-1):
            index = indices[offset]
            box = boxes[index].copy()
            box[[0, 2]] = (box[[0, 2]] - pad_xy[0]) / scale
            box[[1, 3]] = (box[[1, 3]] - pad_xy[1]) / scale
            label = labels[int(cls)] if labels and int(cls) < len(labels) else str(int(cls))
            result.append(PixelDetection(tuple(map(float, box)), float(scores[index]), int(cls), label))
    return validate_detections(result, *original_size)


class ONNXDetector:
    """OpenCV DNN 后端，便于替换为轻量化 ONNX 模型，无需另装 onnxruntime。"""

    def __init__(self, config: Mapping[str, Any]) -> None:
        import cv2
        path = Path(str(_option(config, "model_path", "weights", "")))
        if not path.is_file():
            raise FileNotFoundError(f"ONNX 文件不存在：{path}")
        self.config = dict(config)
        self.output_format = str(config.get("output_format", ""))
        if self.output_format not in ("xyxy_score_class", "yolov8"):
            raise ValueError("必须明确填写 ONNX output_format: xyxy_score_class 或 yolov8")
        size = config.get("input_size", [640, 640])
        self.input_size = (int(size[0]), int(size[1]))  # 宽、高
        if min(self.input_size) <= 0:
            raise ValueError("ONNX 输入宽高必须为正")
        self.net = cv2.dnn.readNetFromONNX(str(path))

    def detect(self, image_bgr: np.ndarray) -> list[PixelDetection]:
        import cv2
        h, w = image_bgr.shape[:2]
        iw, ih = self.input_size
        scale = min(iw / w, ih / h)
        nw, nh = round(w * scale), round(h * scale)
        px, py = (iw - nw) // 2, (ih - nh) // 2
        canvas = np.full((ih, iw, 3), 114, dtype=np.uint8)
        canvas[py:py + nh, px:px + nw] = cv2.resize(image_bgr, (nw, nh))
        self.net.setInput(cv2.dnn.blobFromImage(canvas, 1 / 255.0, self.input_size, swapRB=True))
        names = self.net.getUnconnectedOutLayersNames()
        if len(names) != 1:
            raise ValueError("内置 ONNX 后端仅支持单输出模型；多输出请使用 custom 插件")
        return decode_onnx_output(
            self.net.forward(names[0]), output_format=self.output_format,
            input_size=self.input_size, original_size=(w, h), scale=scale, pad_xy=(px, py),
            confidence=float(self.config.get("confidence", 0.35)),
            iou=float(self.config.get("iou", 0.5)), classes=self.config.get("classes"),
            labels=self.config.get("labels"),
        )


def create_detector(config: Mapping[str, Any]) -> Detector:
    constructors = {"ultralytics": UltralyticsDetector, "yolo": UltralyticsDetector,
                    "onnx": ONNXDetector, "custom": CustomDetector}
    kind = str(config.get("type", "ultralytics"))
    if kind not in constructors:
        raise ValueError(f"未知检测器类型 {kind}；支持 {list(constructors)}")
    return constructors[kind](config)


def _replace_latest(channel: Any, item: Any) -> None:
    """进程间有界邮箱；队列满则丢掉旧帧，不积累延迟。"""
    try:
        channel.put_nowait(item)
    except queue.Full:
        try:
            channel.get_nowait()
        except queue.Empty:
            pass
        try:
            channel.put_nowait(item)
        except queue.Full:
            pass  # multiprocessing feeder 尚未刷新时，允许丢当前帧。


def _capture_process(device_id: str, url: str, options: dict, channel: Any, stop: Any) -> None:
    """此函数必须在模块顶层，Windows spawn 才能序列化。"""
    import cv2
    channel.cancel_join_thread()  # 退出时不等待无人消费的最后一帧被写入管道。
    frame_id = 0
    retry_s = float(options.get("reconnect_s", 1.0))
    while not stop.is_set():
        capture = None
        try:
            params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(options.get("open_timeout_ms", 3000)),
                      cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(options.get("read_timeout_ms", 1000))]
            capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)
            if not capture.isOpened():
                raise RuntimeError("RTSP/视频无法打开")
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # FFmpeg 可能忽略它；有界邮箱仍有效。
            while not stop.is_set():
                ok, image = capture.read()
                if not ok:
                    raise RuntimeError("RTSP/视频读取失败")
                now, utc = time.monotonic(), time.time()
                frame_id += 1
                delay = float(options.get("video_latency_s", 0.0))
                _replace_latest(channel, ("frame", VideoFrame(device_id, frame_id, image, now, now - delay, utc)))
        except Exception as exc:
            _replace_latest(channel, ("error", f"{type(exc).__name__}: {exc}"))
        finally:
            if capture is not None:
                capture.release()
        stop.wait(retry_s)


class LatestFrameSource:
    """每台相机一个可终止的解码进程，start() 不等待网络连接。"""

    def __init__(self, device_id: str, url: str, options: Mapping[str, Any] | None = None) -> None:
        self.device_id, self.url, self.options = device_id, url, dict(options or {})
        self.latest: VideoFrame | None = None
        self.last_error = ""
        self._context = mp.get_context("spawn")
        self._channel = self._context.Queue(maxsize=1)
        self._stop = self._context.Event()
        self._process: Any = None

    def start(self) -> None:
        if self._process is not None:
            return
        self._process = self._context.Process(
            target=_capture_process, args=(self.device_id, self.url, self.options, self._channel, self._stop),
            name=f"video-{self.device_id}", daemon=True,
        )
        self._process.start()

    def poll(self) -> VideoFrame | None:
        while True:
            try:
                kind, value = self._channel.get_nowait()
            except queue.Empty:
                break
            if kind == "frame":
                self.latest, self.last_error = value, ""
            else:
                self.last_error = value
        return self.latest

    def close(self) -> None:
        self._stop.set()
        if self._process is not None:
            self._process.join(timeout=0.5)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=1.0)
            self._process = None
        self._channel.close()


class VisionPipeline:
    """单个模型实例轮流处理各相机最新帧，GPU 推理不会阻塞云台看门狗。

    collect() 返回自上次调用后新完成的 Detection；没有新帧时返回空列表，
    因此同一帧不会被融合器重复当成独立观测。需要更多吞吐量时，可在此边界
    替换为 GPU 批推理或多进程检测，模型输入/输出接口无需变化。
    """

    def __init__(self, cfg: LabConfig, event_sink: Any = None, *,
                 sources: Mapping[str, LatestFrameSource] | None = None,
                 detector: Detector | None = None, detection_enabled: bool = True) -> None:
        self.cfg, self.event_sink = cfg, event_sink
        self.sources = dict(sources) if sources is not None else {
            device.id: LatestFrameSource(device.id, device.rtsp_url or f"rtsp://{device.ip}:8554/main.264", device.camera)
            for device in cfg.active_devices}
        self.detector = detector
        self.detection_enabled = bool(detection_enabled)
        self.max_frame_age_s = float(cfg.system.get("max_frame_age_s", 0.6))
        self._device_configs = {device.id: device for device in cfg.active_devices}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._batches: dict[str, DetectionBatch] = {}
        # 预览快照与融合消费邮箱独立；浏览器刷新不得取走融合器尚未处理的检测。
        self._preview: dict[str, DetectionBatch] = {}
        self._thread: threading.Thread | None = None
        self.errors: dict[str, str] = {}
        self.skipped_frames: dict[str, int] = {key: 0 for key in self.sources}
        self._reported_errors: dict[str, str] = {}

    async def start(self) -> None:
        import asyncio
        if self._thread is not None:
            return
        if self.detection_enabled and self.detector is None:
            # 加载权重/CUDA 初始化也可能耗时；它不占用控制事件循环。
            self.detector = await asyncio.to_thread(create_detector, self.cfg.detector)
        # 停机可在模型加载线程仍工作时到达。加载返回后不能重新拉起已关闭会话的RTSP。
        if self._stop.is_set():
            return
        for source in self.sources.values():
            source.start()
        self._thread = threading.Thread(target=self._run, name="vision-inference", daemon=True)
        self._thread.start()

    def request_stop(self) -> None:
        """无等待地撤销启动/推理授权；close() 随后负责进程回收。"""
        self._stop.set()

    async def set_detection_enabled(self, enabled: bool) -> None:
        """允许纯预览/扫描不加载 YOLO；启用跟踪时按需加载同一个检测器。"""
        import asyncio
        if enabled and self.detector is None:
            self.detector = await asyncio.to_thread(create_detector, self.cfg.detector)
        with self._lock:
            self.detection_enabled = bool(enabled)
            self._batches.clear()

    def preview_batch(self, device_id: str) -> DetectionBatch | None:
        """只读获取最新画面；不会消费 collect()，返回时间用于界面标示陈旧图像。"""
        with self._lock:
            return self._preview.get(device_id)

    def _run(self) -> None:
        seen = {key: 0 for key in self.sources}
        while not self._stop.is_set():
            worked = False
            for key, source in self.sources.items():
                if self._stop.is_set():
                    break
                try:
                    frame = source.poll()
                    if frame is None or frame.frame_id <= seen[key]:
                        continue
                    self.skipped_frames[key] += max(0, frame.frame_id - seen[key] - 1)
                    seen[key] = frame.frame_id
                    if time.monotonic() - frame.capture_monotonic_s > self.max_frame_age_s:
                        continue
                    start = time.monotonic()
                    enabled = self.detection_enabled
                    detections = validate_detections(self.detector.detect(frame.image_bgr),
                                                     frame.image_bgr.shape[1], frame.image_bgr.shape[0]) if enabled else []
                    batch = DetectionBatch(frame, tuple(detections), start, time.monotonic())
                    with self._lock:
                        self._preview[key] = batch
                        if enabled and self.detection_enabled:
                            self._batches[key] = batch
                        self.errors.pop(key, None)
                    worked = True
                except Exception as exc:
                    with self._lock:
                        self.errors[key] = f"{type(exc).__name__}: {exc}"
            if not worked:
                self._stop.wait(0.005)

    def collect_batches(self) -> tuple[DetectionBatch, ...]:
        """供只读预览使用：图像和框一起取出，防止旧框叠到较新的画面上。"""
        with self._lock:
            results = tuple(self._batches.values())
            self._batches.clear()
        now = time.monotonic()
        return tuple(batch for batch in results
                     if now - batch.frame.capture_monotonic_s <= self.max_frame_age_s)

    def collect(self) -> list[Detection]:
        results = self.collect_batches()
        with self._lock:
            errors = dict(self.errors)
        errors.update({key: source.last_error for key, source in self.sources.items() if source.last_error})
        if self.event_sink:
            for key, error in errors.items():
                if self._reported_errors.get(key) != error:
                    self.event_sink("vision_error", {"device_id": key, "t": time.monotonic(), "error": error})
            self._reported_errors = errors
        # 慢推理的结果也检查年龄，不能仅在开始推理前检查。
        now = time.monotonic()
        detections = []
        for batch in results:
            frame = batch.frame
            if now - frame.capture_monotonic_s > self.max_frame_age_s:
                continue
            if self.event_sink:
                self.event_sink("frame", {
                    "device_id": frame.device_id, "frame_id": frame.frame_id,
                    "t": frame.capture_monotonic_s, "received_t": frame.receive_monotonic_s,
                    "received_utc_s": frame.receive_utc_s, "timestamp_kind": frame.timestamp_kind,
                    "inference_ms": (batch.inference_completed_s - batch.inference_started_s) * 1000,
                    "age_ms": (now - frame.capture_monotonic_s) * 1000,
                    "detection_count": len(batch.detections),
                    "skipped_frames": self.skipped_frames[frame.device_id],
                })
            for index, item in enumerate(batch.detections):
                detections.append(Detection(
                    device_id=frame.device_id, frame_id=frame.frame_id, t=frame.capture_monotonic_s,
                    bbox_xyxy=item.bbox_xyxy, confidence=item.confidence, class_id=item.class_id,
                    local_id=item.local_track_id or str(index),
                    image_size=(frame.image_bgr.shape[1], frame.image_bgr.shape[0]),
                    received_t=frame.receive_monotonic_s,
                    time_uncertainty_s=float(self._device_configs[frame.device_id].camera.get("time_uncertainty_s", 0.15)),
                    embedding=item.embedding,
                ))
        return detections

    def _close_sync(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        for source in self.sources.values():
            source.close()
        if self._thread is not None and self._thread.is_alive():
            self.errors["shutdown"] = "推理线程仍在底层模型调用中；它是 daemon，不阻塞进程退出"

    async def close(self) -> None:
        import asyncio
        await asyncio.to_thread(self._close_sync)
