# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""RTSP sub-stream example for new-generation cameras using OpenCV.

Demonstrates receiving the secondary (low-resolution) stream from a new-gen
SIYI camera. The sub stream is available only on new-generation cameras
(ZT30, ZT6, and later) at /video2.

Old-gen cameras (ZR10, ZR30, A8 Mini, A2 Mini, R1M) do NOT expose a sub
stream via RTSP. Sub-stream access on old-gen uses the SIYI FPV private UDP
protocol which is not implemented in this SDK.

Target cameras: ZT30, ZT6 (new-gen only).
Stream URL: rtsp://192.168.144.25:8554/video2
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

WINDOW_TITLE = "SIYI — Sub Stream (/video2)"


async def main() -> None:
    """Receive and display the sub stream from a new-gen SIYI camera."""
    try:
        import cv2  # type: ignore[import]
    except ImportError:
        print("opencv-python is required. Install with: pip install opencv-python")
        return

    rtsp_url = build_rtsp_url(generation=CameraGeneration.NEW, stream="sub")
    print(f"Connecting to sub stream: {rtsp_url}")
    print("Note: sub stream is only available on new-gen cameras (ZT30, ZT6+).")

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
        print("Streaming. Press Ctrl+C to stop.")
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
