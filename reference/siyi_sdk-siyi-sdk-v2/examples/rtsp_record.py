# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Record 30 seconds of RTSP video from a new-gen camera to output.mp4.

Demonstrates using cv2.VideoWriter to save a SIYI RTSP stream to an MP4
file. Progress is printed every second.

Target cameras: ZT30, ZT6 (and later new-gen models).
Stream URL: rtsp://192.168.144.25:8554/video1
Output file: output.mp4
"""

from __future__ import annotations

import asyncio
import time

from siyi_sdk import (
    CameraGeneration,
    SIYIStream,
    StreamBackend,
    StreamConfig,
    StreamFrame,
    build_rtsp_url,
    configure_logging,
)

_RECORD_SECONDS = 30


async def main() -> None:
    """Record 30 seconds of the main stream to output.mp4."""
    try:
        import cv2  # type: ignore[import]
    except ImportError:
        print("opencv-python is required. Install with: pip install opencv-python")
        return

    rtsp_url = build_rtsp_url(generation=CameraGeneration.NEW, stream="main")
    print(f"Connecting to: {rtsp_url}")

    config = StreamConfig(rtsp_url=rtsp_url, backend=StreamBackend.OPENCV)
    stream = SIYIStream(config)

    writer: cv2.VideoWriter | None = None  # type: ignore[name-defined]
    frame_count = 0
    start_time: float | None = None

    def on_frame(frame: StreamFrame) -> None:
        nonlocal writer, frame_count, start_time

        if start_time is None:
            start_time = time.monotonic()

        if writer is None:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # type: ignore[attr-defined]
            writer = cv2.VideoWriter(  # type: ignore[attr-defined]
                "output.mp4", fourcc, 25.0, (frame.width, frame.height)
            )
            print(f"Recording {frame.width}x{frame.height} to output.mp4")

        writer.write(frame.frame)
        frame_count += 1

    stream.on_frame(on_frame)

    try:
        await stream.start()
        print(f"Recording for {_RECORD_SECONDS}s. Press Ctrl+C to stop early.")
        for elapsed in range(_RECORD_SECONDS):
            await asyncio.sleep(1.0)
            print(
                f"  {elapsed + 1}/{_RECORD_SECONDS}s — frames: {frame_count}  "
                f"FPS: {stream.fps:.1f}"
            )
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        await stream.stop()
        if writer is not None:
            writer.release()
        print(f"Saved {frame_count} frames to output.mp4")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
