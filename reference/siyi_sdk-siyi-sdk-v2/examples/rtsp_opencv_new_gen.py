# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""RTSP video stream example for new-generation cameras (ZT30/ZT6) using OpenCV.

Demonstrates receiving the main stream from a ZT30 or ZT6 camera via the
OpenCV backend and displaying frames with cv2.imshow. The camera must be
accessible at the default IP 192.168.144.25.

Target cameras: ZT30, ZT6 (and later new-gen models).
Stream URL: rtsp://192.168.144.25:8554/video1
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

WINDOW_TITLE = "SIYI ZT30/ZT6 — Main Stream"


async def main() -> None:
    """Receive and display the main stream from a new-gen SIYI camera."""
    try:
        import cv2  # type: ignore[import]
    except ImportError:
        print("opencv-python is required. Install with: pip install opencv-python")
        return

    rtsp_url = build_rtsp_url(generation=CameraGeneration.NEW, stream="main")
    print(f"Connecting to: {rtsp_url}")

    config = StreamConfig(
        rtsp_url=rtsp_url,
        backend=StreamBackend.OPENCV,
    )
    stream = SIYIStream(config)

    latest: list[StreamFrame | None] = [None]
    lock = threading.Lock()

    def on_frame(frame: StreamFrame) -> None:
        with lock:
            latest[0] = frame

    stream.on_frame(on_frame)

    stop_display = threading.Event()

    def display_loop() -> None:
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
