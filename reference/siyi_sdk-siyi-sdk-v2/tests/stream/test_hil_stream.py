# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Hardware-in-the-loop test — skipped unless SIYI_HIL=1 and camera reachable."""

from __future__ import annotations

import asyncio
import os

import pytest

from siyi_sdk.stream import CameraGeneration, SIYIStream, StreamConfig, build_rtsp_url


@pytest.mark.hil
@pytest.mark.skipif(os.environ.get("SIYI_HIL") != "1", reason="HIL gate: set SIYI_HIL=1")
async def test_rtsp_receives_frames_opencv() -> None:
    """Verify that OpenCV receives at least one frame from a live camera in 3 s."""
    import cv2  # noqa: F401  # camera test requires OpenCV

    config = StreamConfig(
        rtsp_url=build_rtsp_url(generation=CameraGeneration.NEW),
        backend="opencv",  # type: ignore[arg-type]
    )
    stream = SIYIStream(config)
    frames: list[object] = []
    stream.on_frame(lambda f: frames.append(f))
    await stream.start()
    await asyncio.sleep(3)
    await stream.stop()
    assert len(frames) > 0, "Expected at least one frame in 3 seconds"
    assert stream.fps >= 0.0
