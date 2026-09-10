# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Shared fixtures and mock backend for stream tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import numpy as np
import pytest

from siyi_sdk.stream.base import AbstractStreamBackend
from siyi_sdk.stream.models import StreamConfig, StreamFrame


class MockStreamBackend(AbstractStreamBackend):
    """Yields a fixed list of frames then stops.

    Suitable for injecting into SIYIStream via monkeypatching _select_backend.
    """

    BACKEND_NAME = "mock"

    def __init__(self, config: StreamConfig, frames: list[StreamFrame]) -> None:
        super().__init__(config)
        self._frames = frames
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    def frame_available(self) -> bool:
        return bool(self._frames)

    def read_frame_nowait(self) -> StreamFrame | None:
        return self._frames[0] if self._frames else None

    async def frame_generator(self) -> AsyncGenerator[StreamFrame, None]:
        for frame in self._frames:
            await asyncio.sleep(0)
            yield frame


@pytest.fixture
def sample_frame() -> StreamFrame:
    """A single 1280x720 black frame."""
    return StreamFrame(
        frame=np.zeros((720, 1280, 3), dtype=np.uint8),
        timestamp=0.0,
        width=1280,
        height=720,
        backend="mock",
    )


@pytest.fixture
def stream_config() -> StreamConfig:
    """Default StreamConfig pointing at the standard new-gen URL."""
    return StreamConfig(rtsp_url="rtsp://192.168.144.25:8554/video1")
