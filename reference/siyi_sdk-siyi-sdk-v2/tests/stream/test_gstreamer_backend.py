# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for GStreamerBackend.

Skipped if PyGObject (gi) is not importable.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

gi = pytest.importorskip("gi")

from siyi_sdk.stream.gstreamer_backend import _H264_PIPELINE, GStreamerBackend  # noqa: E402
from siyi_sdk.stream.models import StreamConfig  # noqa: E402

_ = _H264_PIPELINE  # reference to avoid unused-import error when gi is available


@pytest.fixture
def config() -> StreamConfig:
    return StreamConfig(rtsp_url="rtsp://192.168.144.25:8554/video1", latency_ms=200)


class TestGStreamerBackendInit:
    def test_raises_if_gst_unavailable(self, config: StreamConfig) -> None:
        with (
            patch("siyi_sdk.stream.gstreamer_backend._GST_AVAILABLE", False),
            pytest.raises(ImportError, match="PyGObject"),
        ):
            GStreamerBackend(config)

    def test_config_stored(self, config: StreamConfig) -> None:
        backend = GStreamerBackend(config)
        assert backend._config is config


class TestGStreamerPipelineString:
    def test_url_in_pipeline(self, config: StreamConfig) -> None:
        backend = GStreamerBackend(config)
        pipeline_str = backend._build_pipeline_str()
        assert config.rtsp_url in pipeline_str

    def test_tcp_protocol_in_pipeline(self, config: StreamConfig) -> None:
        backend = GStreamerBackend(config)
        pipeline_str = backend._build_pipeline_str()
        assert "protocols=tcp" in pipeline_str

    def test_udp_protocol_in_pipeline(self) -> None:
        cfg = StreamConfig(rtsp_url="rtsp://x", transport="udp")
        backend = GStreamerBackend(cfg)
        pipeline_str = backend._build_pipeline_str()
        assert "protocols=udp" in pipeline_str

    def test_latency_in_pipeline(self, config: StreamConfig) -> None:
        backend = GStreamerBackend(config)
        pipeline_str = backend._build_pipeline_str()
        assert f"latency={config.latency_ms}" in pipeline_str

    def test_h265_pipeline_used(self, config: StreamConfig) -> None:
        backend = GStreamerBackend(config, codec="h265")
        pipeline_str = backend._build_pipeline_str()
        assert "rtph265depay" in pipeline_str
        assert "h265parse" in pipeline_str

    def test_h264_pipeline_used_by_default(self, config: StreamConfig) -> None:
        backend = GStreamerBackend(config)
        pipeline_str = backend._build_pipeline_str()
        assert "rtph264depay" in pipeline_str
        assert "h264parse" in pipeline_str
