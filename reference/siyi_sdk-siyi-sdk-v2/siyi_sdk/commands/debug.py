# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Debug and ArduPilot-specific command encoders and decoders (0x27-0x2A, 0x70, 0x71).

This module implements encoding/decoding for debug and weak control commands including:
- Control mode query
- Weak threshold parameters
- Motor voltage query
- Weak control mode
"""

from __future__ import annotations

import struct

from siyi_sdk.constants import (
    CMD_REQUEST_CONTROL_MODE,
    CMD_REQUEST_MOTOR_VOLTAGE,
    CMD_REQUEST_WEAK_CONTROL_MODE,
    CMD_REQUEST_WEAK_THRESHOLD,
    CMD_SET_WEAK_CONTROL_MODE,
    CMD_SET_WEAK_THRESHOLD,
)
from siyi_sdk.exceptions import MalformedPayloadError, ResponseError
from siyi_sdk.models import ControlMode, MotorVoltage, WeakControlThreshold


def encode_get_control_mode() -> bytes:
    """Encode get control mode request (0x27).

    ArduPilot only.

    Returns:
        Empty payload.

    """
    return b""


def decode_control_mode(payload: bytes) -> ControlMode:
    """Decode control mode response (0x27).

    Args:
        payload: 1-byte control mode (0-4).

    Returns:
        ControlMode enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_CONTROL_MODE,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (mode,) = struct.unpack("<B", payload)
    return ControlMode(mode)


def encode_get_weak_threshold() -> bytes:
    """Encode get weak threshold request (0x28).

    ArduPilot only.

    Returns:
        Empty payload.

    """
    return b""


def decode_weak_threshold(payload: bytes) -> WeakControlThreshold:
    """Decode weak threshold response (0x28).

    Args:
        payload: 6 bytes (3 x int16 LE, divided by 10).

    Returns:
        WeakControlThreshold dataclass.

    Raises:
        MalformedPayloadError: If payload length is not 6 bytes.

    """
    if len(payload) != 6:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_WEAK_THRESHOLD,
            reason=f"expected 6 bytes, got {len(payload)}",
        )
    limit, voltage, angular_error = struct.unpack("<hhh", payload)
    return WeakControlThreshold(
        limit=limit / 10.0,
        voltage=voltage / 10.0,
        angular_error=angular_error / 10.0,
    )


def encode_set_weak_threshold(t: WeakControlThreshold) -> bytes:
    """Encode set weak threshold request (0x29).

    ArduPilot only.

    Args:
        t: WeakControlThreshold dataclass.

    Returns:
        6-byte payload (3 x int16 LE, multiplied by 10).

    """
    return struct.pack(
        "<hhh",
        round(t.limit * 10),
        round(t.voltage * 10),
        round(t.angular_error * 10),
    )


def decode_set_weak_threshold_ack(payload: bytes) -> bool:
    """Decode set weak threshold acknowledgment (0x29).

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
            cmd_id=CMD_SET_WEAK_THRESHOLD,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (sta,) = struct.unpack("<B", payload)
    if sta == 0:
        raise ResponseError(cmd_id=CMD_SET_WEAK_THRESHOLD, sta=sta)
    return True


def encode_get_motor_voltage() -> bytes:
    """Encode get motor voltage request (0x2A).

    ArduPilot only.

    Returns:
        Empty payload.

    """
    return b""


def decode_motor_voltage(payload: bytes) -> MotorVoltage:
    """Decode motor voltage response (0x2A).

    Args:
        payload: 6 bytes (3 x int16 LE, divided by 1000).

    Returns:
        MotorVoltage dataclass with voltages in volts.

    Raises:
        MalformedPayloadError: If payload length is not 6 bytes.

    """
    if len(payload) != 6:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_MOTOR_VOLTAGE,
            reason=f"expected 6 bytes, got {len(payload)}",
        )
    yaw, pitch, roll = struct.unpack("<hhh", payload)
    return MotorVoltage(
        yaw=yaw / 1000.0,
        pitch=pitch / 1000.0,
        roll=roll / 1000.0,
    )


def encode_get_weak_control_mode() -> bytes:
    """Encode get weak control mode request (0x70).

    Returns:
        Empty payload.

    """
    return b""


def decode_weak_control_mode(payload: bytes) -> bool:
    """Decode weak control mode response (0x70).

    Args:
        payload: 1-byte mode state.

    Returns:
        True if weak control mode is enabled.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_WEAK_CONTROL_MODE,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (mode,) = struct.unpack("<B", payload)
    return bool(mode)


def encode_set_weak_control_mode(on: bool) -> bytes:
    """Encode set weak control mode request (0x71).

    Args:
        on: True to enable weak control mode.

    Returns:
        1-byte payload (uint8).

    """
    return struct.pack("<B", int(on))


def decode_set_weak_control_mode_ack(payload: bytes) -> bool:
    """Decode set weak control mode acknowledgment (0x71).

    Args:
        payload: 2 bytes (sta, weak_mode_state).

    Returns:
        True if now enabled.

    Raises:
        MalformedPayloadError: If payload length is not 2 bytes.
        ResponseError: If status is 0 (failure).

    """
    if len(payload) != 2:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_WEAK_CONTROL_MODE,
            reason=f"expected 2 bytes, got {len(payload)}",
        )
    sta, weak_mode_state = struct.unpack("<BB", payload)
    if sta == 0:
        raise ResponseError(cmd_id=CMD_SET_WEAK_CONTROL_MODE, sta=sta)
    return bool(weak_mode_state)
