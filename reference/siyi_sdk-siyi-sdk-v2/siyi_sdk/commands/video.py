# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Video command encoders and decoders (0x10, 0x11).

This module implements encoding/decoding for video stitching mode commands.
"""

from __future__ import annotations

import struct

from siyi_sdk.constants import CMD_REQUEST_VIDEO_STITCHING_MODE, CMD_SET_VIDEO_STITCHING_MODE
from siyi_sdk.exceptions import ConfigurationError, MalformedPayloadError
from siyi_sdk.models import VideoStitchingMode


def encode_get_video_stitching_mode() -> bytes:
    """Encode get video stitching mode request (0x10).

    Returns:
        Empty payload.

    """
    return b""


def decode_video_stitching_mode(payload: bytes) -> VideoStitchingMode:
    """Decode video stitching mode response (0x10).

    Args:
        payload: 1-byte mode.

    Returns:
        VideoStitchingMode enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_VIDEO_STITCHING_MODE,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (mode,) = struct.unpack("<B", payload)
    return VideoStitchingMode(mode)


def encode_set_video_stitching_mode(mode: VideoStitchingMode) -> bytes:
    """Encode set video stitching mode request (0x11).

    Args:
        mode: Video stitching mode (0-8).

    Returns:
        1-byte payload (uint8).

    Raises:
        ConfigurationError: If mode is not a valid VideoStitchingMode.

    """
    if not isinstance(mode, VideoStitchingMode):
        raise ConfigurationError(f"mode must be a VideoStitchingMode, got {mode}")
    return struct.pack("<B", mode)


def decode_set_video_stitching_mode_ack(payload: bytes) -> VideoStitchingMode:
    """Decode set video stitching mode acknowledgment (0x11).

    Args:
        payload: 1-byte mode.

    Returns:
        VideoStitchingMode enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_VIDEO_STITCHING_MODE,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (mode,) = struct.unpack("<B", payload)
    return VideoStitchingMode(mode)
