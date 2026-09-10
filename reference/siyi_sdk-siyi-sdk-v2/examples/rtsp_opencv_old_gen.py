# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""RTSP video stream example for old-generation cameras using OpenCV.

Demonstrates receiving the single RTSP stream from an old-generation SIYI
camera (ZR10, ZR30, A8 Mini, A2 Mini, R1M). These cameras expose only one
RTSP stream at rtsp://<host>:8554/main.264 — sub-stream access requires the
SIYI FPV private UDP protocol which is not implemented here.

Target cameras: ZR10, ZR30, A8 Mini, A2 Mini, R1M.
Stream URL: rtsp://192.168.144.25:8554/main.264
"""

from __future__ import annotations

import asyncio
import threading

from siyi_sdk import (
    CameraGeneration,
    SIYIStream,
    StreamBackend,
    StreamConfig,
    StreamFrame,
    build_rtsp_url,
    configure_logging,
)

WINDOW_TITLE = "SIYI Old-Gen — Main Stream"


async def main() -> None:
    """Receive and display the main stream from an old-gen SIYI camera."""
    try:
        import cv2  # type: ignore[import]
    except ImportError:
        print("opencv-python is required. Install with: pip install opencv-python")
        return

    rtsp_url = build_rtsp_url(generation=CameraGeneration.OLD, stream="main")
    print(f"Connecting to: {rtsp_url}")

    config = StreamConfig(
        rtsp_url=rtsp_url,
        backend=StreamBackend.OPENCV,
    )
    stream = SIYIStream(config)

    # Latest frame shared between the async callback and the display thread.
    latest: list[StreamFrame | None] = [None]
    lock = threading.Lock()

    def on_frame(frame: StreamFrame) -> None:
        with lock:
            latest[0] = frame

    stream.on_frame(on_frame)

    stop_display = threading.Event()

    def display_loop() -> None:
        """Dedicated GUI thread — owns the OpenCV window and pumps Qt events."""
        cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
        while not stop_display.is_set():
            with lock:
                frame = latest[0]
            if frame is not None:
                cv2.imshow(WINDOW_TITLE, frame.frame)
            if cv2.waitKey(5) & 0xFF == ord("q"):
                stop_display.set()
                break

    display_thread = threading.Thread(target=display_loop, name="siyi-display", daemon=True)
    display_thread.start()

    try:
        await stream.start()
        print(f"Streaming at {rtsp_url}. Press Ctrl+C to stop.")
        print("Note: old-gen cameras only expose a single RTSP stream.")
        while not stop_display.is_set():
            await asyncio.sleep(1.0)
            print(f"FPS: {stream.fps:.1f}")
    except KeyboardInterrupt:
        pass
    finally:
        stop_display.set()
        await stream.stop()
        display_thread.join(timeout=2.0)
        cv2.destroyAllWindows()
        print("Stream stopped.")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
