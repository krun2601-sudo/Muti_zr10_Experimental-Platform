# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Gimbal command encoders and decoders (0x07, 0x08, 0x0E, 0x19, 0x41).

This module implements encoding/decoding for gimbal control commands including:
- Rotation control
- One-key centering
- Set attitude
- Gimbal mode query
- Single-axis attitude control
"""

from __future__ import annotations

import struct

from siyi_sdk.constants import (
    CMD_GIMBAL_ROTATION,
    CMD_ONE_KEY_CENTERING,
    CMD_REQUEST_GIMBAL_MODE,
    CMD_SET_GIMBAL_ATTITUDE,
    CMD_SINGLE_AXIS_ATTITUDE,
)
from siyi_sdk.exceptions import ConfigurationError, MalformedPayloadError, ResponseError
from siyi_sdk.models import CenteringAction, GimbalMotionMode, SetAttitudeAck


def encode_rotation(yaw: int, pitch: int) -> bytes:
    """Encode gimbal rotation request (0x07).

    Args:
        yaw: Yaw speed (-100 to +100).
        pitch: Pitch speed (-100 to +100).

    Returns:
        2-byte payload (2 x int8).

    Raises:
        ConfigurationError: If speeds are out of range.

    """
    if not -100 <= yaw <= 100:
        raise ConfigurationError(f"yaw must be in [-100,100], got {yaw}")
    if not -100 <= pitch <= 100:
        raise ConfigurationError(f"pitch must be in [-100,100], got {pitch}")
    return struct.pack("<bb", yaw, pitch)


def decode_rotation_ack(payload: bytes) -> None:
    """Decode gimbal rotation acknowledgment (0x07).

    Args:
        payload: 1-byte status.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.
        ResponseError: If status is 0 (failure).

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_GIMBAL_ROTATION,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (sta,) = struct.unpack("<B", payload)
    if sta == 0:
        raise ResponseError(cmd_id=CMD_GIMBAL_ROTATION, sta=sta)


def encode_one_key_centering(action: CenteringAction) -> bytes:
    """Encode one-key centering request (0x08).

    Args:
        action: Centering action (1=center, 2=down, 3=center, 4=down).

    Returns:
        1-byte payload (uint8).

    Raises:
        ConfigurationError: If action is not in {1, 2, 3, 4}.

    """
    if action not in (
        CenteringAction.ONE_KEY_CENTER,
        CenteringAction.CENTER_DOWNWARD,
        CenteringAction.CENTER,
        CenteringAction.DOWNWARD,
    ):
        raise ConfigurationError(f"action must be a valid CenteringAction, got {action}")
    return struct.pack("<B", action)


def decode_one_key_centering_ack(payload: bytes) -> None:
    """Decode one-key centering acknowledgment (0x08).

    Args:
        payload: 1-byte status.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.
        ResponseError: If status is 0 (failure).

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_ONE_KEY_CENTERING,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (sta,) = struct.unpack("<B", payload)
    if sta == 0:
        raise ResponseError(cmd_id=CMD_ONE_KEY_CENTERING, sta=sta)


def encode_set_attitude(yaw_deg: float, pitch_deg: float) -> bytes:
    """Encode set gimbal attitude request (0x0E).

    Args:
        yaw_deg: Target yaw angle in degrees.
        pitch_deg: Target pitch angle in degrees.

    Returns:
        4-byte payload (2 x int16 LE, angles x 10).

    """
    yaw_raw = round(yaw_deg * 10)
    pitch_raw = round(pitch_deg * 10)
    return struct.pack("<hh", yaw_raw, pitch_raw)


def decode_set_attitude_ack(payload: bytes) -> SetAttitudeAck:
    """Decode set gimbal attitude acknowledgment (0x0E).

    Args:
        payload: 6 bytes (3 x int16 LE, angles x 10).

    Returns:
        SetAttitudeAck dataclass with current yaw, pitch, roll in degrees.

    Raises:
        MalformedPayloadError: If payload length is not 6 bytes.

    """
    if len(payload) != 6:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_GIMBAL_ATTITUDE,
            reason=f"expected 6 bytes, got {len(payload)}",
        )
    yaw_raw, pitch_raw, roll_raw = struct.unpack("<hhh", payload)
    return SetAttitudeAck(
        yaw_deg=yaw_raw / 10.0,
        pitch_deg=pitch_raw / 10.0,
        roll_deg=roll_raw / 10.0,
    )


def encode_gimbal_mode() -> bytes:
    """Encode gimbal mode request (0x19).

    Returns:
        Empty payload.

    """
    return b""


def decode_gimbal_mode(payload: bytes) -> GimbalMotionMode:
    """Decode gimbal mode response (0x19).

    Args:
        payload: 1-byte mode.

    Returns:
        GimbalMotionMode enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_GIMBAL_MODE,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (mode,) = struct.unpack("<B", payload)
    return GimbalMotionMode(mode)


def encode_single_axis(angle_deg: float, axis: int) -> bytes:
    """Encode single-axis attitude control request (0x41).

    Args:
        angle_deg: Target angle in degrees.
        axis: Axis selection (0=yaw, 1=pitch).

    Returns:
        3-byte payload (int16 LE angle x 10, uint8 axis).

    Raises:
        ConfigurationError: If axis is not 0 or 1.

    """
    if axis not in (0, 1):
        raise ConfigurationError(f"axis must be 0 or 1, got {axis}")
    angle_raw = round(angle_deg * 10)
    return struct.pack("<hB", angle_raw, axis)


def decode_single_axis_ack(payload: bytes) -> SetAttitudeAck:
    """Decode single-axis attitude acknowledgment (0x41).

    Args:
        payload: 6 bytes (3 x int16 LE, angles x 10).

    Returns:
        SetAttitudeAck dataclass with current yaw, pitch, roll in degrees.

    Raises:
        MalformedPayloadError: If payload length is not 6 bytes.

    """
    if len(payload) != 6:
        raise MalformedPayloadError(
            cmd_id=CMD_SINGLE_AXIS_ATTITUDE,
            reason=f"expected 6 bytes, got {len(payload)}",
        )
    yaw_raw, pitch_raw, roll_raw = struct.unpack("<hhh", payload)
    return SetAttitudeAck(
        yaw_deg=yaw_raw / 10.0,
        pitch_deg=pitch_raw / 10.0,
        roll_deg=roll_raw / 10.0,
    )
