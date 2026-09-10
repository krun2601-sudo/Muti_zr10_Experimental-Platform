# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""AI tracking command encoders and decoders (0x4D, 0x4E, 0x50, 0x51).

This module implements encoding/decoding for AI tracking commands including:
- AI mode status
- AI tracking stream status
- AI tracking target data
- AI stream output control
"""

from __future__ import annotations

import struct

from siyi_sdk.constants import (
    CMD_AI_TRACK_STREAM,
    CMD_GET_AI_MODE_STA,
    CMD_GET_AI_TRACK_STREAM_STA,
    CMD_SET_AI_TRACK_STREAM_STA,
)
from siyi_sdk.exceptions import MalformedPayloadError, ResponseError
from siyi_sdk.models import AIStreamStatus, AITargetID, AITrackingTarget, AITrackStatus


def encode_get_ai_mode() -> bytes:
    """Encode get AI mode status request (0x4D).

    Returns:
        Empty payload.

    """
    return b""


def decode_ai_mode(payload: bytes) -> bool:
    """Decode AI mode status response (0x4D).

    Args:
        payload: 1-byte AI mode status (0=off, 1=on).

    Returns:
        True if AI mode is enabled.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_GET_AI_MODE_STA,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (sta,) = struct.unpack("<B", payload)
    return bool(sta)


def encode_get_ai_stream_status() -> bytes:
    """Encode get AI tracking stream status request (0x4E).

    Returns:
        Empty payload.

    """
    return b""


def decode_ai_stream_status(payload: bytes) -> AIStreamStatus:
    """Decode AI tracking stream status response (0x4E).

    Args:
        payload: 1-byte stream status (0-3).

    Returns:
        AIStreamStatus enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_GET_AI_TRACK_STREAM_STA,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (sta,) = struct.unpack("<B", payload)
    return AIStreamStatus(sta)


def decode_ai_tracking(payload: bytes) -> AITrackingTarget:
    """Decode AI tracking stream push (0x50).

    Args:
        payload: 10 bytes (4xuint16 LE + 2xuint8).

    Returns:
        AITrackingTarget dataclass.

    Raises:
        MalformedPayloadError: If payload length is not 10 bytes.

    """
    if len(payload) != 10:
        raise MalformedPayloadError(
            cmd_id=CMD_AI_TRACK_STREAM,
            reason=f"expected 10 bytes, got {len(payload)}",
        )
    x, y, w, h, target_id, status = struct.unpack("<HHHHBB", payload)
    return AITrackingTarget(
        x=x,
        y=y,
        w=w,
        h=h,
        target_id=AITargetID(target_id),
        status=AITrackStatus(status),
    )


def encode_set_ai_stream_output(on: bool) -> bytes:
    """Encode set AI tracking stream output request (0x51).

    Args:
        on: True to enable AI tracking stream (1=on, 0=off).

    Returns:
        1-byte payload (uint8).

    """
    return struct.pack("<B", int(on))


def decode_set_ai_stream_output_ack(payload: bytes) -> bool:
    """Decode set AI tracking stream output acknowledgment (0x51).

    Args:
        payload: 1-byte status.

    Returns:
        True if successful.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.
        ResponseError: If status is 0 (failure).

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_AI_TRACK_STREAM_STA,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (sta,) = struct.unpack("<B", payload)
    if sta == 0:
        raise ResponseError(cmd_id=CMD_SET_AI_TRACK_STREAM_STA, sta=sta)
    return True
