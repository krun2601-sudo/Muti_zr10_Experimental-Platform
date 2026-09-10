# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Focus command encoders and decoders (0x04, 0x06).

This module implements encoding/decoding for focus control commands including:
- Auto focus
- Manual focus
"""

from __future__ import annotations

import struct

from siyi_sdk.constants import CMD_AUTO_FOCUS, CMD_MANUAL_FOCUS
from siyi_sdk.exceptions import ConfigurationError, MalformedPayloadError, ResponseError


def encode_auto_focus(auto_focus: int, touch_x: int, touch_y: int) -> bytes:
    """Encode auto focus request (0x04).

    Args:
        auto_focus: Auto focus mode (0=disable, 1=enable).
        touch_x: Touch X coordinate (0-65535).
        touch_y: Touch Y coordinate (0-65535).

    Returns:
        5-byte payload (uint8 + 2 x uint16 LE).

    Raises:
        ConfigurationError: If parameters are out of range.

    """
    if not 0 <= auto_focus <= 255:
        raise ConfigurationError(f"auto_focus must be in [0,255], got {auto_focus}")
    if not 0 <= touch_x <= 0xFFFF:
        raise ConfigurationError(f"touch_x must be in [0,65535], got {touch_x}")
    if not 0 <= touch_y <= 0xFFFF:
        raise ConfigurationError(f"touch_y must be in [0,65535], got {touch_y}")
    return struct.pack("<BHH", auto_focus, touch_x, touch_y)


def decode_auto_focus_ack(payload: bytes) -> None:
    """Decode auto focus acknowledgment (0x04).

    Args:
        payload: 1-byte status.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.
        ResponseError: If status is 0 (failure).

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_AUTO_FOCUS,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (sta,) = struct.unpack("<B", payload)
    if sta == 0:
        raise ResponseError(cmd_id=CMD_AUTO_FOCUS, sta=sta)


def encode_manual_focus(direction: int) -> bytes:
    """Encode manual focus request (0x06).

    Args:
        direction: Focus direction (-1=near, 0=stop, 1=far).

    Returns:
        1-byte payload (int8).

    Raises:
        ConfigurationError: If direction is not in {-1, 0, 1}.

    """
    if direction not in (-1, 0, 1):
        raise ConfigurationError(f"direction must be in {{-1,0,1}}, got {direction}")
    return struct.pack("<b", direction)


def decode_manual_focus_ack(payload: bytes) -> None:
    """Decode manual focus acknowledgment (0x06).

    Args:
        payload: 1-byte status.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.
        ResponseError: If status is 0 (failure).

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_MANUAL_FOCUS,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (sta,) = struct.unpack("<B", payload)
    if sta == 0:
        raise ResponseError(cmd_id=CMD_MANUAL_FOCUS, sta=sta)
