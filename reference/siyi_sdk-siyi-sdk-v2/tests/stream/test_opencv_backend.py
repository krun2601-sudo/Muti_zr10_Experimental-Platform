# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for OpenCVBackend.

Skipped if cv2 is not importable.
"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from siyi_sdk.stream.models import StreamConfig, StreamFrame, build_rtsp_url  # noqa: E402
from siyi_sdk.stream.opencv_backend import OpenCVBackend  # noqa: E402


@pytest.fixture
def config() -> StreamConfig:
    return StreamConfig(rtsp_url="rtsp://192.168.144.25:8554/video1", buffer_size=2)


class TestOpenCVBackendInit:
    def test_raises_if_cv2_unavailable(self, config: StreamConfig) -> None:
        with (
            patch("siyi_sdk.stream.opencv_backend._OPENCV_AVAILABLE", False),
            pytest.raises(ImportError, match="opencv-python"),
        ):
            OpenCVBackend(config)

    def test_config_stored(self, config: StreamConfig) -> None:
        backend = OpenCVBackend(config)
        assert backend._config is config


class TestOpenCVBackendConnect:
    async def test_thread_started(self, config: StreamConfig) -> None:
        backend = OpenCVBackend(config)
        with patch.object(backend, "_capture_loop"):
            await backend.connect()
            assert backend._thread is not None
            assert backend._thread.daemon
            await backend.disconnect()

    async def test_queue_created(self, config: StreamConfig) -> None:
        backend = OpenCVBackend(config)
        with patch.object(backend, "_capture_loop"):
            await backend.connect()
            assert backend._queue is not None
            await backend.disconnect()


class TestOpenCVBackendFrameCapture:
    async def test_frame_created_correctly(self, config: StreamConfig) -> None:
        """Mock cap.read() to return a fake BGR frame and verify StreamFrame."""
        fake_img = np.zeros((480, 640, 3), dtype=np.uint8)
        fake_img[0, 0, 0] = 42  # distinctive pixel

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.side_effect = [(True, fake_img), (False, None)]

        backend = OpenCVBackend(config)

        with patch("siyi_sdk.stream.opencv_backend.cv2") as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            mock_cv2.CAP_FFMPEG = 1900  # type: ignore[attr-defined]
            mock_cv2.CAP_PROP_BUFFERSIZE = 38  # type: ignore[attr-defined]

            await backend.connect()
            # Wait briefly for thread to process
            await asyncio.sleep(0.2)

        received_frames = list(backend._latest)
        await backend.disconnect()

        assert len(received_frames) >= 1
        sf: StreamFrame = received_frames[0]
        assert sf.width == 640
        assert sf.height == 480
        assert sf.backend == "opencv"

    async def test_buffer_size_set(self, config: StreamConfig) -> None:
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (False, None)

        with patch("siyi_sdk.stream.opencv_backend.cv2") as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            mock_cv2.CAP_FFMPEG = 1900
            mock_cv2.CAP_PROP_BUFFERSIZE = 38

            backend = OpenCVBackend(config)
            await backend.connect()
            await asyncio.sleep(0.1)

        set_calls = [c for c in mock_cap.set.call_args_list if c.args[0] == 38]
        await backend.disconnect()
        assert len(set_calls) >= 1
        assert set_calls[0].args[1] == config.buffer_size


class TestOpenCVBackendRtspUrl:
    def test_build_rtsp_url_matches_config(self) -> None:
        url = build_rtsp_url(host="192.168.144.25", stream="main")
        cfg = StreamConfig(rtsp_url=url)
        backend = OpenCVBackend(cfg)
        assert backend._config.rtsp_url == "rtsp://192.168.144.25:8554/video1"


class TestOpenCVBackendDisconnect:
    async def test_disconnect_stops_thread(self, config: StreamConfig) -> None:
        backend = OpenCVBackend(config)
        # Patch _capture_loop to block until the stop event is set so the
        # thread stays alive long enough for the is_alive() assertion.
        ready = threading.Event()

        def blocking_loop() -> None:
            ready.set()
            backend._stop_event.wait()

        with patch.object(backend, "_capture_loop", side_effect=blocking_loop):
            await backend.connect()
            ready.wait(timeout=1.0)  # ensure thread is running
            thread = backend._thread
            assert thread is not None
            assert thread.is_alive()
            await backend.disconnect()
            assert not thread.is_alive()

    async def test_frame_available_false_initially(self, config: StreamConfig) -> None:
        backend = OpenCVBackend(config)
        assert not backend.frame_available()

    async def test_read_frame_nowait_none_initially(self, config: StreamConfig) -> None:
        backend = OpenCVBackend(config)
        assert backend.read_frame_nowait() is None
