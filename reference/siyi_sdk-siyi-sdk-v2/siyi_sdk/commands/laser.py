# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Laser ranging command encoders and decoders (0x15, 0x17, 0x32).

This module implements encoding/decoding for laser ranging commands including:
- Laser distance measurement
- Laser target lat/lon
- Laser ranging state control
"""

from __future__ import annotations

import struct

from siyi_sdk.constants import (
    CMD_REQUEST_LASER_DISTANCE,
    CMD_REQUEST_LASER_LATLON,
    CMD_SET_LASER_RANGING_STATE,
    LASER_MIN_RAW_DM,
)
from siyi_sdk.exceptions import MalformedPayloadError, ResponseError
from siyi_sdk.models import LaserDistance, LaserTargetLatLon


def encode_laser_distance() -> bytes:
    """Encode laser distance request (0x15).

    Returns:
        Empty payload.

    """
    return b""


def decode_laser_distance(payload: bytes) -> LaserDistance:
    """Decode laser distance response (0x15).

    Args:
        payload: 2 bytes (uint16 LE raw distance in decimeters).

    Returns:
        LaserDistance dataclass with distance_m in meters or None if out of range.

    Raises:
        MalformedPayloadError: If payload length is not 2 bytes.

    """
    if len(payload) != 2:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_LASER_DISTANCE,
            reason=f"expected 2 bytes, got {len(payload)}",
        )
    (raw,) = struct.unpack("<H", payload)
    # Per spec: raw < 50 or raw == 0 → out of range
    if raw == 0 or raw < LASER_MIN_RAW_DM:
        return LaserDistance(distance_m=None)
    return LaserDistance(distance_m=raw / 10.0)


def encode_laser_target_latlon() -> bytes:
    """Encode laser target lat/lon request (0x17).

    Returns:
        Empty payload.

    """
    return b""


def decode_laser_target_latlon(payload: bytes) -> LaserTargetLatLon:
    """Decode laser target lat/lon response (0x17).

    Args:
        payload: 8 bytes (2 x int32 LE in degrees x 10^7).

    Returns:
        LaserTargetLatLon dataclass.

    Raises:
        MalformedPayloadError: If payload length is not 8 bytes.

    """
    if len(payload) != 8:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_LASER_LATLON,
            reason=f"expected 8 bytes, got {len(payload)}",
        )
    lon_e7, lat_e7 = struct.unpack("<ii", payload)
    return LaserTargetLatLon(lat_e7=lat_e7, lon_e7=lon_e7)


def encode_set_laser_ranging_state(on: bool) -> bytes:
    """Encode set laser ranging state request (0x32).

    Args:
        on: True to enable laser ranging.

    Returns:
        1-byte payload (uint8).

    """
    return struct.pack("<B", int(on))


def decode_set_laser_ranging_state_ack(payload: bytes) -> bool:
    """Decode set laser ranging state acknowledgment (0x32).

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
            cmd_id=CMD_SET_LASER_RANGING_STATE,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (sta,) = struct.unpack("<B", payload)
    if sta == 0:
        raise ResponseError(cmd_id=CMD_SET_LASER_RANGING_STATE, sta=sta)
    return True
