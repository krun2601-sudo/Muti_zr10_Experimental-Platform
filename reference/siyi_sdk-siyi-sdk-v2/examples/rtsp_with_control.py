# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Simultaneous gimbal control and RTSP video streaming.

Demonstrates using SIYIClient for gimbal control at the same time as an RTSP
video stream. Both communication channels operate concurrently:
  - SIYIClient sends control commands over UDP (port 37260).
  - SIYIStream receives video over RTSP (port 8554).

The script subscribes to the attitude push stream and prints the gimbal
attitude alongside the current video FPS every second.

Target cameras: ZT30, ZT6 (new-gen) at 192.168.144.25.
"""

from __future__ import annotations

import asyncio
import threading

from siyi_sdk import (
    CameraGeneration,
    SIYIClient,
    StreamFrame,
    configure_logging,
    connect_udp,
)
from siyi_sdk.models import DataStreamFreq, GimbalAttitude, GimbalDataType

WINDOW_TITLE = "SIYI Stream"


async def main() -> None:
    """Connect gimbal control + RTSP stream, display frames, and print combined telemetry."""
    try:
        import cv2  # type: ignore[import]
    except ImportError:
        print("opencv-python is required for display. Install with: pip install opencv-python")
        return

    client: SIYIClient = await connect_udp("192.168.144.25", 37260)

    stream = client.create_stream(
        stream="main",
        generation=CameraGeneration.NEW,
    )

    frame_count = 0
    latest: list[StreamFrame | None] = [None]
    lock = threading.Lock()

    def on_frame(frame: StreamFrame) -> None:
        nonlocal frame_count
        frame_count += 1
        with lock:
            latest[0] = frame

    stream.on_frame(on_frame)

    last_attitude: GimbalAttitude | None = None

    def on_attitude(att: GimbalAttitude) -> None:
        nonlocal last_attitude
        last_attitude = att

    client.on_attitude(on_attitude)

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
        await client.request_gimbal_stream(GimbalDataType.ATTITUDE, DataStreamFreq.HZ10)
        await stream.start()
        print("Gimbal control + RTSP stream active. Press Ctrl+C to stop.")

        for _ in range(30):  # run for 30 seconds
            if stop_display.is_set():
                break
            await asyncio.sleep(1.0)
            att_str = (
                f"yaw={last_attitude.yaw_deg:.1f}°  "
                f"pitch={last_attitude.pitch_deg:.1f}°"
                if last_attitude
                else "attitude: (waiting...)"
            )
            print(f"FPS: {stream.fps:.1f}  |  {att_str}  |  frames: {frame_count}")

    except KeyboardInterrupt:
        pass
    finally:
        stop_display.set()
        await stream.stop()
        await client.close()
        display_thread.join(timeout=2.0)
        cv2.destroyAllWindows()
        print("Stopped.")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
