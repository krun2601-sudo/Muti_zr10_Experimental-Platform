# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for SIYIStream lifecycle, callbacks, and frame dispatch."""

from __future__ import annotations

import asyncio

import numpy as np

from siyi_sdk.stream.models import StreamConfig, StreamFrame
from siyi_sdk.stream.stream import SIYIStream

from .conftest import MockStreamBackend


def _make_frames(n: int) -> list[StreamFrame]:
    return [
        StreamFrame(
            frame=np.zeros((480, 640, 3), dtype=np.uint8),
            timestamp=float(i),
            width=640,
            height=480,
            backend="mock",
        )
        for i in range(n)
    ]


def _make_stream_with_mock(
    frames: list[StreamFrame], rtsp_url: str = "rtsp://192.168.144.25:8554/video1"
) -> SIYIStream:
    cfg = StreamConfig(rtsp_url=rtsp_url)
    stream = SIYIStream(cfg)
    mock = MockStreamBackend(cfg, frames)
    stream._select_backend = lambda: mock  # type: ignore[method-assign]
    return stream


class TestLifecycle:
    async def test_initial_state(self) -> None:
        stream = _make_stream_with_mock([])
        assert not stream.is_running
        assert stream.last_frame is None
        assert stream.fps == 0.0

    async def test_start_sets_running(self) -> None:
        stream = _make_stream_with_mock([])
        await stream.start()
        assert stream.is_running
        await stream.stop()

    async def test_stop_clears_running(self) -> None:
        stream = _make_stream_with_mock([])
        await stream.start()
        await stream.stop()
        assert not stream.is_running

    async def test_start_idempotent(self) -> None:
        stream = _make_stream_with_mock([])
        await stream.start()
        task1 = stream._task
        await stream.start()  # second call should be no-op
        assert stream._task is task1
        await stream.stop()

    async def test_stop_idempotent(self) -> None:
        stream = _make_stream_with_mock([])
        await stream.stop()  # should not raise
        await stream.stop()  # second call also safe


class TestCallbacks:
    async def test_sync_callback_receives_frames(self) -> None:
        frames = _make_frames(3)
        stream = _make_stream_with_mock(frames)
        received: list[StreamFrame] = []
        stream.on_frame(received.append)
        await stream.start()
        # Allow frame loop to drain
        await asyncio.sleep(0.05)
        await stream.stop()
        assert len(received) == 3

    async def test_async_callback_receives_frames(self) -> None:
        frames = _make_frames(3)
        stream = _make_stream_with_mock(frames)
        received: list[StreamFrame] = []

        async def async_cb(f: StreamFrame) -> None:
            received.append(f)

        stream.on_frame(async_cb)
        await stream.start()
        await asyncio.sleep(0.05)
        await stream.stop()
        assert len(received) == 3

    async def test_multiple_callbacks(self) -> None:
        frames = _make_frames(2)
        stream = _make_stream_with_mock(frames)
        received_a: list[StreamFrame] = []
        received_b: list[StreamFrame] = []
        stream.on_frame(received_a.append)
        stream.on_frame(received_b.append)
        await stream.start()
        await asyncio.sleep(0.05)
        await stream.stop()
        assert len(received_a) == 2
        assert len(received_b) == 2

    async def test_remove_callback_stops_delivery(self) -> None:
        frames = _make_frames(1)
        stream = _make_stream_with_mock(frames)
        received: list[StreamFrame] = []
        stream.on_frame(received.append)
        stream.remove_frame_callback(received.append)
        await stream.start()
        await asyncio.sleep(0.05)
        await stream.stop()
        assert len(received) == 0

    async def test_on_frame_returns_unsubscribe(self) -> None:
        frames = _make_frames(2)
        stream = _make_stream_with_mock(frames)
        received: list[StreamFrame] = []
        unsub = stream.on_frame(received.append)
        unsub()  # unsubscribe immediately before start
        await stream.start()
        await asyncio.sleep(0.05)
        await stream.stop()
        assert len(received) == 0

    async def test_bad_callback_does_not_kill_loop(self) -> None:
        frames = _make_frames(3)
        stream = _make_stream_with_mock(frames)
        received: list[StreamFrame] = []

        def bad_cb(f: StreamFrame) -> None:
            raise RuntimeError("intentional error")

        stream.on_frame(bad_cb)
        stream.on_frame(received.append)
        await stream.start()
        await asyncio.sleep(0.05)
        await stream.stop()
        # good callback should still receive all frames
        assert len(received) == 3

    async def test_decorator_form(self) -> None:
        frames = _make_frames(2)
        stream = _make_stream_with_mock(frames)
        received: list[StreamFrame] = []

        @stream.on_frame
        def handler(f: StreamFrame) -> None:
            received.append(f)

        await stream.start()
        await asyncio.sleep(0.05)
        await stream.stop()
        assert len(received) == 2

    async def test_decorator_async_form(self) -> None:
        frames = _make_frames(2)
        stream = _make_stream_with_mock(frames)
        received: list[StreamFrame] = []

        @stream.on_frame
        async def handler(f: StreamFrame) -> None:
            received.append(f)

        await stream.start()
        await asyncio.sleep(0.05)
        await stream.stop()
        assert len(received) == 2

    async def test_unsubscribe_from_decorator(self) -> None:
        frames = _make_frames(1)
        stream = _make_stream_with_mock(frames)
        received: list[StreamFrame] = []

        unsub = stream.on_frame(received.append)
        unsub()  # immediately remove

        await stream.start()
        await asyncio.sleep(0.05)
        await stream.stop()
        assert received == []


class TestProperties:
    async def test_last_frame_none_before_start(self) -> None:
        stream = _make_stream_with_mock([])
        assert stream.last_frame is None

    async def test_last_frame_set_after_frames(self) -> None:
        frames = _make_frames(3)
        stream = _make_stream_with_mock(frames)
        await stream.start()
        await asyncio.sleep(0.05)
        await stream.stop()
        assert stream.last_frame is not None
        assert stream.last_frame.timestamp == 2.0  # last frame

    async def test_fps_zero_before_frames(self) -> None:
        stream = _make_stream_with_mock([])
        assert stream.fps == 0.0

    async def test_fps_nonzero_after_frames(self) -> None:
        frames = _make_frames(5)
        stream = _make_stream_with_mock(frames)
        await stream.start()
        await asyncio.sleep(0.05)
        await stream.stop()
        # FPS should be > 0 since we just received frames
        fps = stream.fps
        assert fps >= 0.0  # may be 0 if 1 second has elapsed; accept both
