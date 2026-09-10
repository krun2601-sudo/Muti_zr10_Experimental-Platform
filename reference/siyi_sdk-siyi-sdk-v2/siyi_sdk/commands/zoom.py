# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Zoom command encoders and decoders (0x05, 0x0F, 0x16, 0x18).

This module implements encoding/decoding for zoom control commands including:
- Manual zoom with auto focus
- Absolute zoom
- Zoom range query
- Current zoom query
"""

from __future__ import annotations

import struct

from siyi_sdk.constants import (
    CMD_ABSOLUTE_ZOOM_AUTO_FOCUS,
    CMD_MANUAL_ZOOM_AUTO_FOCUS,
    CMD_REQUEST_ZOOM_MAGNIFICATION,
    CMD_REQUEST_ZOOM_RANGE,
)
from siyi_sdk.exceptions import ConfigurationError, MalformedPayloadError, ResponseError
from siyi_sdk.models import CurrentZoom, ZoomRange


def encode_manual_zoom(direction: int) -> bytes:
    """Encode manual zoom request (0x05).

    Args:
        direction: Zoom direction (-1=zoom out, 0=stop, 1=zoom in).

    Returns:
        1-byte payload (int8).

    Raises:
        ConfigurationError: If direction is not in {-1, 0, 1}.

    """
    if direction not in (-1, 0, 1):
        raise ConfigurationError(f"direction must be in {{-1,0,1}}, got {direction}")
    return struct.pack("<b", direction)


def decode_manual_zoom_ack(payload: bytes) -> float:
    """Decode manual zoom acknowledgment (0x05).

    Args:
        payload: 2-byte zoom multiple (uint16 LE).

    Returns:
        Current zoom magnification (raw / 10.0).

    Raises:
        MalformedPayloadError: If payload length is not 2 bytes.

    """
    if len(payload) != 2:
        raise MalformedPayloadError(
            cmd_id=CMD_MANUAL_ZOOM_AUTO_FOCUS,
            reason=f"expected 2 bytes, got {len(payload)}",
        )
    (zoom_raw,) = struct.unpack("<H", payload)
    return float(zoom_raw) / 10.0


def encode_absolute_zoom(zoom: float) -> bytes:
    """Encode absolute zoom request (0x0F).

    Args:
        zoom: Target zoom magnification (1.0 to 30.0).

    Returns:
        2-byte payload (uint8 int_part, uint8 float_part).

    Raises:
        ConfigurationError: If zoom is out of valid range or precision.

    """
    if not 1.0 <= zoom <= 30.0:
        raise ConfigurationError(f"zoom must be in [1.0, 30.0], got {zoom}")

    int_part = int(zoom)
    float_part = round((zoom - int_part) * 10)

    # Handle rounding edge case: 4.95 rounds to int_part=4, float_part=10
    if float_part == 10:
        int_part += 1
        float_part = 0

    if not 1 <= int_part <= 0x1E:
        raise ConfigurationError(f"zoom int_part must be in [1,30], got {int_part}")
    if not 0 <= float_part <= 9:
        raise ConfigurationError(f"zoom float_part must be in [0,9], got {float_part}")

    return struct.pack("<BB", int_part, float_part)


def decode_absolute_zoom_ack(payload: bytes) -> None:
    """Decode absolute zoom acknowledgment (0x0F).

    Args:
        payload: 1-byte acknowledgment.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.
        ResponseError: If acknowledgment is 0 (failure).

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_ABSOLUTE_ZOOM_AUTO_FOCUS,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (ack,) = struct.unpack("<B", payload)
    if ack == 0:
        raise ResponseError(cmd_id=CMD_ABSOLUTE_ZOOM_AUTO_FOCUS, sta=ack)


def encode_zoom_range() -> bytes:
    """Encode zoom range request (0x16).

    Returns:
        Empty payload.

    """
    return b""


def decode_zoom_range(payload: bytes) -> ZoomRange:
    """Decode zoom range response (0x16).

    Args:
        payload: 2 bytes (uint8 max_int, uint8 max_float).

    Returns:
        ZoomRange dataclass.

    Raises:
        MalformedPayloadError: If payload length is not 2 bytes.

    """
    if len(payload) != 2:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_ZOOM_RANGE,
            reason=f"expected 2 bytes, got {len(payload)}",
        )
    max_int, max_float = struct.unpack("<BB", payload)
    return ZoomRange(max_int=max_int, max_float=max_float)


def encode_current_zoom() -> bytes:
    """Encode current zoom request (0x18).

    Returns:
        Empty payload.

    """
    return b""


def decode_current_zoom(payload: bytes) -> CurrentZoom:
    """Decode current zoom response (0x18).

    Args:
        payload: 2 bytes (uint8 integer, uint8 decimal).

    Returns:
        CurrentZoom dataclass.

    Raises:
        MalformedPayloadError: If payload length is not 2 bytes.

    """
    if len(payload) != 2:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_ZOOM_MAGNIFICATION,
            reason=f"expected 2 bytes, got {len(payload)}",
        )
    integer, decimal = struct.unpack("<BB", payload)
    return CurrentZoom(integer=integer, decimal=decimal)
