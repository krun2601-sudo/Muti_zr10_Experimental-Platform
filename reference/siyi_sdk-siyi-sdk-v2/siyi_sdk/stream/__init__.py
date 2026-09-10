# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""SIYI camera RTSP video streaming.

Provides SIYIStream and related types for receiving live video from SIYI cameras
via RTSP. Three backends are supported: OpenCV (default fallback), GStreamer
(lowest latency, hardware acceleration), and aiortsp + PyAV (pure-Python async).
"""

from __future__ import annotations

from .models import (
    CAMERA_GENERATION_MAP,
    CameraGeneration,
    StreamBackend,
    StreamConfig,
    StreamFrame,
    build_rtsp_url,
)
from .stream import SIYIStream

__all__ = [
    "CAMERA_GENERATION_MAP",
    "CameraGeneration",
    "SIYIStream",
    "StreamBackend",
    "StreamConfig",
    "StreamFrame",
    "build_rtsp_url",
]
