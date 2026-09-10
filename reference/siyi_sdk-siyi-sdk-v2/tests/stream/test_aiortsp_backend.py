# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for AiortspBackend.

Skipped if aiortsp is not importable.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

aiortsp = pytest.importorskip("aiortsp")

from siyi_sdk.stream.aiortsp_backend import AiortspBackend  # noqa: E402
from siyi_sdk.stream.models import StreamConfig  # noqa: E402


@pytest.fixture
def config() -> StreamConfig:
    return StreamConfig(rtsp_url="rtsp://192.168.144.25:8554/video1")


class TestAiortspBackendInit:
    def test_raises_if_aiortsp_unavailable(self, config: StreamConfig) -> None:
        with (
            patch("siyi_sdk.stream.aiortsp_backend._AIORTSP_AVAILABLE", False),
            pytest.raises(ImportError, match="aiortsp"),
        ):
            AiortspBackend(config)

    def test_config_stored(self, config: StreamConfig) -> None:
        backend = AiortspBackend(config)
        assert backend._config is config


class TestAiortspBackendUrl:
    def test_rtsp_url_stored_in_config(self, config: StreamConfig) -> None:
        backend = AiortspBackend(config)
        assert backend._config.rtsp_url == "rtsp://192.168.144.25:8554/video1"

    async def test_connect_sets_connected(self, config: StreamConfig) -> None:
        backend = AiortspBackend(config)
        await backend.connect()
        assert backend._connected
        await backend.disconnect()
        assert not backend._connected

    async def test_frame_available_false_initially(self, config: StreamConfig) -> None:
        backend = AiortspBackend(config)
        assert not backend.frame_available()

    async def test_read_frame_nowait_none_initially(self, config: StreamConfig) -> None:
        backend = AiortspBackend(config)
        assert backend.read_frame_nowait() is None
