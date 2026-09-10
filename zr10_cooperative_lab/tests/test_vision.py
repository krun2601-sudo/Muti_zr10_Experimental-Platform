"""用小型确定性数组验证检测解码、帧时钟及丢旧帧语义。"""
import asyncio
import time

import numpy as np
import pytest

from zr10lab.config import DeviceConfig, LabConfig
from zr10lab.vision import (DetectionBatch, PixelDetection, VideoFrame, VisionPipeline,
                           create_detector, decode_onnx_output, validate_detections)


def decode(arr, fmt="xyxy_score_class", **kwargs):
    return decode_onnx_output(np.asarray(arr), output_format=fmt, input_size=(640, 640),
                              original_size=(1280, 720), scale=0.5, pad_xy=(0, 140),
                              confidence=0.3, iou=0.5, **kwargs)


def test_letterbox_onnx_xyxy_restores_original_pixels_and_classwise_nms():
    boxes = decode([[100, 200, 200, 300, .9, 0], [101, 201, 199, 299, .8, 0],
                    [100, 200, 200, 300, .85, 1]])
    assert len(boxes) == 2
    assert boxes[0].bbox_xyxy == (200, 120, 400, 320)
    assert {box.class_id for box in boxes} == {0, 1}


def test_yolov8_explicit_layout_and_class_filter():
    # shape=(1,4+C,N)，这里 C=2, N=1。
    arr = np.array([[[150], [250], [100], [100], [.9], [.1]]])
    boxes = decode(arr, "yolov8", classes=[0])
    assert len(boxes) == 1 and boxes[0].bbox_xyxy == (200, 120, 400, 320)
    assert decode(arr, "yolov8", classes=[1]) == []


@pytest.mark.parametrize("arr,fmt", [([[1, 2]], "xyxy_score_class"),
                                     ([[1, 2, 3, 4, float("nan"), 0]], "xyxy_score_class"),
                                     ([[1, 2, 3, 4, .5, .2]], "xyxy_score_class"),
                                     ([[1, 2, 3, 4, .5, 0]], "guess")])
def test_onnx_invalid_or_ambiguous_output_is_rejected(arr, fmt):
    with pytest.raises(ValueError):
        decode(arr, fmt)


def test_detector_requires_user_weights_and_never_downloads_default():
    with pytest.raises(FileNotFoundError):
        create_detector({"type": "ultralytics", "model_path": "missing_weights.pt"})
    with pytest.raises(ValueError):
        create_detector({"type": "guess"})
    with pytest.raises(ValueError, match="冲突"):
        create_detector({"type": "yolo", "model_path": "one.pt", "weights": "two.pt"})
    with pytest.raises(FileNotFoundError):
        create_detector({"type": "yolo", "weights": "missing.pt", "imgsz": 320})


def test_detection_bounds_and_nonfinite():
    boxes = validate_detections([PixelDetection((-5, -5, 110, 80), .8)], 100, 60)
    assert boxes[0].bbox_xyxy == (0, 0, 99, 59)
    with pytest.raises(ValueError):
        validate_detections([PixelDetection((1, 2, float("nan"), 4), .8)], 100, 60)


class FakeSource:
    last_error = ""

    def __init__(self, frame):
        self.frame = frame
        self.closed = False

    def start(self):
        pass

    def poll(self):
        return self.frame

    def close(self):
        self.closed = True


class FakeDetector:
    def detect(self, image):
        return [PixelDetection((10, 10, 20, 20), .9, 0, "drone")]


def test_pipeline_emits_each_frame_once_and_preserves_capture_estimate():
    async def check():
        now = time.monotonic()
        frame = VideoFrame("25", 1, np.zeros((60, 100, 3), dtype=np.uint8), now, now - .02, time.time())
        source = FakeSource(frame)
        cfg = LabConfig([DeviceConfig("25", camera={"time_uncertainty_s": .12})])
        events = []
        pipeline = VisionPipeline(cfg, lambda kind, data: events.append((kind, data)),
                                  sources={"25": source}, detector=FakeDetector())
        await pipeline.start()
        result = []
        for _ in range(20):
            result = pipeline.collect()
            if result:
                break
            await asyncio.sleep(.005)
        assert len(result) == 1
        assert result[0].t == now - .02
        assert result[0].received_t == now
        assert result[0].image_size == (100, 60)
        assert result[0].time_uncertainty_s == .12
        assert pipeline.collect() == []
        assert events[0][1]["timestamp_kind"] == "host_receive_estimate"
        await pipeline.close()
        assert source.closed
    asyncio.run(check())


def test_slow_inference_old_batch_is_dropped_after_completion():
    now = time.monotonic()
    cfg = LabConfig([DeviceConfig("25")], system={"max_frame_age_s": .1})
    pipeline = VisionPipeline(cfg, sources={}, detector=FakeDetector())
    frame = VideoFrame("25", 1, np.zeros((60, 100, 3), dtype=np.uint8), now - 1, now - 1, 0)
    pipeline._batches["25"] = DetectionBatch(frame, (PixelDetection((1, 1, 2, 2), .9),), now - 1, now)
    assert pipeline.collect() == []


def test_viewer_scales_box_and_builds_four_camera_grid_without_gui():
    from zr10lab.viewer import compose_grid, render_tile
    now = time.monotonic()
    frame = VideoFrame("25", 7, np.zeros((100, 200, 3), dtype=np.uint8), now, now, 0)
    box = PixelDetection((20, 20, 40, 40), .9)
    tile = render_tile("25", frame, (box,), width=400, height=234, now=now)
    # 原图放大2倍，顶部34像素；框左上角应在 (40,74)。
    assert tuple(tile[74, 40]) == (0, 230, 120)
    waiting = render_tile("26", None, width=400, height=234)
    grid = compose_grid([tile, waiting, tile, waiting])
    assert grid.shape == (468, 800, 3)


def test_collect_batches_keeps_inference_image_paired_with_its_boxes():
    now = time.monotonic()
    cfg = LabConfig([DeviceConfig("25")])
    pipeline = VisionPipeline(cfg, sources={}, detector=FakeDetector())
    frame = VideoFrame("25", 9, np.zeros((60, 100, 3), dtype=np.uint8), now, now, 0)
    batch = DetectionBatch(frame, (PixelDetection((1, 1, 2, 2), .9),), now, now)
    pipeline._batches["25"] = batch
    assert pipeline.collect_batches() == (batch,)
    assert pipeline.collect_batches() == ()
