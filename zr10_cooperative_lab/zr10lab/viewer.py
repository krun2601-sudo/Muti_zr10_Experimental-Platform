"""只读多路视频查看器：完全不建立 UDP 控制连接，也不发送云台动作。

运行：python -m zr10lab.viewer --config configs/four_zr10.yaml [--detect]
按 Q / Esc 或关闭窗口退出。检测在后台执行，显示的框始终属于同一张图像。
"""
from __future__ import annotations

import argparse
import asyncio
import math
import time
from typing import Any

import numpy as np

from .config import load_config
from .vision import DetectionBatch, LatestFrameSource, PixelDetection, VideoFrame, VisionPipeline, create_detector


def render_tile(device_id: str, frame: VideoFrame | None, detections: tuple[PixelDetection, ...] = (),
                *, width: int = 640, height: int = 394, now: float | None = None,
                status: str = "", max_age_s: float = 0.6) -> np.ndarray:
    """纯图像函数，便于无 GUI 测试。letterbox 缩放和框使用同一尺度及偏移。"""
    import cv2
    now = time.monotonic() if now is None else now
    canvas = np.full((height, width, 3), (24, 24, 24), dtype=np.uint8)
    header_h = 34
    color = (120, 200, 120)
    if frame is None:
        message = f"{device_id} | WAITING FOR VIDEO"
        cv2.putText(canvas, "No frame received", (18, height // 2), cv2.FONT_HERSHEY_SIMPLEX, .7,
                    (170, 170, 170), 1, cv2.LINE_AA)
    else:
        ih, iw = frame.image_bgr.shape[:2]
        scale = min(width / iw, (height - header_h) / ih)
        rw, rh = max(1, round(iw * scale)), max(1, round(ih * scale))
        ox, oy = (width - rw) // 2, header_h + (height - header_h - rh) // 2
        canvas[oy:oy + rh, ox:ox + rw] = cv2.resize(frame.image_bgr, (rw, rh))
        age = now - frame.capture_monotonic_s
        stale = age > max_age_s
        color = (0, 170, 255) if stale else (120, 230, 120)
        message = f"{device_id} | frame {frame.frame_id} | age {age * 1000:.0f} ms"
        if stale:
            message += " STALE"
        for item in detections:
            x1, y1, x2, y2 = item.bbox_xyxy
            a = (round(ox + x1 * scale), round(oy + y1 * scale))
            b = (round(ox + x2 * scale), round(oy + y2 * scale))
            cv2.rectangle(canvas, a, b, (0, 230, 120), 2)
            # OpenCV Hershey 字体不含中文，标签用 class_id 保证跨平台可读。
            label = f"class {item.class_id} {item.confidence:.2f}"
            cv2.putText(canvas, label, (a[0], max(header_h + 14, a[1] - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, .45, (0, 230, 120), 1, cv2.LINE_AA)
    cv2.putText(canvas, message, (10, 23), cv2.FONT_HERSHEY_SIMPLEX, .47, color, 1, cv2.LINE_AA)
    if status:
        cv2.rectangle(canvas, (0, height - 24), (width, height), (25, 25, 25), -1)
        cv2.putText(canvas, status[:85], (10, height - 7), cv2.FONT_HERSHEY_SIMPLEX, .4,
                    (220, 220, 220), 1, cv2.LINE_AA)
    return canvas


def compose_grid(tiles: list[np.ndarray], columns: int | None = None) -> np.ndarray:
    if not tiles:
        raise ValueError("没有需要显示的设备")
    columns = columns or math.ceil(math.sqrt(len(tiles)))
    rows = math.ceil(len(tiles) / columns)
    h, w = tiles[0].shape[:2]
    canvas = np.zeros((rows * h, columns * w, 3), dtype=np.uint8)
    for i, tile in enumerate(tiles):
        canvas[(i // columns) * h:(i // columns + 1) * h, (i % columns) * w:(i % columns + 1) * w] = tile
    return canvas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZR10 多路只读视频预览；不发送云台控制命令")
    parser.add_argument("--config", default="configs/four_zr10.yaml", help="实验 YAML 配置路径")
    parser.add_argument("--detect", action="store_true", help="加载配置的检测模型，后台推理并画框")
    parser.add_argument("--tile-width", type=int, default=640, help="每路显示宽度（像素）")
    parser.add_argument("--fps", type=float, default=20, help="界面最大刷新频率，不改变设备编码帧率")
    args = parser.parse_args(argv)
    if args.tile_width < 256 or not math.isfinite(args.fps) or not 1 <= args.fps <= 120:
        parser.error("tile-width 必须至少 256，fps 必须在 1..120")
    cfg = load_config(args.config)
    import cv2
    window = "ZR10 Cooperative Lab | Read-only video | Q / Esc to quit"
    sources: dict[str, LatestFrameSource] = {}
    pipeline: VisionPipeline | None = None
    displayed: dict[str, DetectionBatch] = {}
    try:
        # 先检查 GUI，失败时尚未启动任何 RTSP 子进程。
        cv2.namedWindow(window, cv2.WINDOW_NORMAL)
        sources = {d.id: LatestFrameSource(d.id, d.rtsp_url or f"rtsp://{d.ip}:8554/main.264", d.camera)
                   for d in cfg.active_devices}
        if args.detect:
            detector = create_detector(cfg.detector)
            pipeline = VisionPipeline(cfg, sources=sources, detector=detector)
            asyncio.run(pipeline.start())
        else:
            for source in sources.values():
                source.start()
        print("只读视频预览已启动。Q / Esc 或关闭窗口退出；没有连接云台控制通道。")
        print("age 是主机接收时刻修正后的估计帧龄，不是经硬件验证的端到端曝光延迟。")
        while True:
            begin = time.monotonic()
            if pipeline:
                for batch in pipeline.collect_batches():
                    displayed[batch.frame.device_id] = batch
            tiles = []
            for key, source in sources.items():
                # 检测开启时只有推理线程消费源队列，主界面仅读取其不可变最新帧快照。
                frame = source.latest if pipeline else source.poll()
                boxes: tuple[PixelDetection, ...] = ()
                status = "VIDEO ONLY"
                if pipeline:
                    batch = displayed.get(key)
                    if batch is not None and begin - batch.frame.capture_monotonic_s <= pipeline.max_frame_age_s:
                        frame, boxes = batch.frame, batch.detections
                        status = f"DETECT {(batch.inference_completed_s - batch.inference_started_s) * 1000:.0f} ms | {len(boxes)} objects"
                    else:
                        status = "WAITING FOR FRESH INFERENCE"
                    if pipeline.errors.get(key):
                        status = "DETECTOR ERROR: " + pipeline.errors[key]
                if source.last_error:
                    status = "VIDEO ERROR: " + source.last_error
                tiles.append(render_tile(key, frame, boxes, width=args.tile_width,
                                          height=round(args.tile_width * 9 / 16) + 34,
                                          now=begin, status=status,
                                          max_age_s=float(cfg.system.get("max_frame_age_s", .6))))
            cv2.imshow(window, compose_grid(tiles))
            keypress = cv2.waitKey(1) & 0xFF
            if keypress in (27, ord("q"), ord("Q")) or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
            time.sleep(max(0, 1 / args.fps - (time.monotonic() - begin)))
    except cv2.error as exc:
        print("OpenCV 预览不可用。请在支持桌面的环境安装 opencv-python；不要同时安装 headless 与 GUI 两个发行包。")
        print(f"OpenCV: {exc}")
        return 2
    except KeyboardInterrupt:
        pass
    finally:
        if pipeline:
            asyncio.run(pipeline.close())
        else:
            for source in sources.values():
                source.close()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
