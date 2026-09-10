# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""System command encoders and decoders (0x00, 0x01, 0x02, 0x30, 0x31, 0x40, 0x80, 0x81, 0x82).

This module implements encoding/decoding for system-level commands including:
- Heartbeat
- Firmware version
- Hardware ID
- UTC time
- System time
- Soft reboot
- IP configuration
"""

from __future__ import annotations

import struct
from ipaddress import IPv4Address

from siyi_sdk.constants import (
    CMD_GET_IP,
    CMD_REQUEST_FIRMWARE_VERSION,
    CMD_REQUEST_GIMBAL_SYSTEM_INFO,
    CMD_REQUEST_HARDWARE_ID,
    CMD_REQUEST_SYSTEM_TIME,
    CMD_SET_IP,
    CMD_SET_UTC_TIME,
    CMD_SOFT_REBOOT,
    UINT64_MAX,
)
from siyi_sdk.exceptions import ConfigurationError, MalformedPayloadError, ResponseError
from siyi_sdk.models import FirmwareVersion, GimbalSystemInfo, HardwareID, IPConfig, SystemTime


def encode_heartbeat() -> bytes:
    """Encode TCP heartbeat request (0x00).

    Returns:
        Empty payload (heartbeat has no payload).

    """
    return b""


def encode_firmware_version() -> bytes:
    """Encode firmware version request (0x01).

    Returns:
        Empty payload.

    """
    return b""


def decode_firmware_version(payload: bytes) -> FirmwareVersion:
    """Decode firmware version response (0x01).

    Args:
        payload: 8-byte payload (camera + gimbal, no zoom) or 12-byte payload
            (camera + gimbal + zoom). Cameras without optical zoom (e.g. A8 Mini)
            return 8 bytes; zoom is set to 0 in that case.

    Returns:
        FirmwareVersion dataclass with camera, gimbal, zoom version words.

    Raises:
        MalformedPayloadError: If payload length is not 8 or 12 bytes.

    """
    if len(payload) == 8:
        camera, gimbal = struct.unpack("<II", payload)
        return FirmwareVersion(camera=camera, gimbal=gimbal, zoom=0)
    if len(payload) == 12:
        camera, gimbal, zoom = struct.unpack("<III", payload)
        return FirmwareVersion(camera=camera, gimbal=gimbal, zoom=zoom)
    raise MalformedPayloadError(
        cmd_id=CMD_REQUEST_FIRMWARE_VERSION,
        reason=f"expected 8 or 12 bytes, got {len(payload)}",
    )


def encode_hardware_id() -> bytes:
    """Encode hardware ID request (0x02).

    Returns:
        Empty payload.

    """
    return b""


def decode_hardware_id(payload: bytes) -> HardwareID:
    """Decode hardware ID response (0x02).

    Args:
        payload: 12-byte raw hardware ID.

    Returns:
        HardwareID dataclass with raw bytes.

    Raises:
        MalformedPayloadError: If payload length is not 12 bytes.

    """
    if len(payload) != 12:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_HARDWARE_ID,
            reason=f"expected 12 bytes, got {len(payload)}",
        )
    return HardwareID(raw=payload)


def encode_set_utc_time(unix_usec: int) -> bytes:
    """Encode set UTC time request (0x30).

    Args:
        unix_usec: UNIX epoch time in microseconds.

    Returns:
        8-byte payload containing uint64 LE.

    Raises:
        ConfigurationError: If unix_usec is negative or out of range.

    """
    if unix_usec < 0:
        raise ConfigurationError(f"unix_usec must be non-negative, got {unix_usec}")
    if unix_usec > UINT64_MAX:
        raise ConfigurationError(f"unix_usec exceeds uint64 range: {unix_usec}")
    return struct.pack("<Q", unix_usec)


def decode_set_utc_time_ack(payload: bytes) -> bool:
    """Decode set UTC time acknowledgment (0x30).

    Args:
        payload: 1-byte acknowledgment.

    Returns:
        True if successful.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.
        ResponseError: If acknowledgment is 0 (failure).

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_UTC_TIME,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (ack,) = struct.unpack("<b", payload)
    if ack == 0:
        raise ResponseError(cmd_id=CMD_SET_UTC_TIME, sta=ack)
    return True


def encode_gimbal_system_info() -> bytes:
    """Encode gimbal system info request (0x31).

    Returns:
        Empty payload.

    """
    return b""


def decode_gimbal_system_info(payload: bytes) -> GimbalSystemInfo:
    """Decode gimbal system info response (0x31).

    Args:
        payload: 1-byte laser state.

    Returns:
        GimbalSystemInfo dataclass.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_GIMBAL_SYSTEM_INFO,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (laser_state,) = struct.unpack("<B", payload)
    return GimbalSystemInfo(laser_state=bool(laser_state))


def encode_system_time() -> bytes:
    """Encode system time request (0x40).

    Returns:
        Empty payload.

    """
    return b""


def decode_system_time(payload: bytes) -> SystemTime:
    """Decode system time response (0x40).

    Args:
        payload: 12 bytes (uint64 unix_usec + uint32 boot_ms).

    Returns:
        SystemTime dataclass.

    Raises:
        MalformedPayloadError: If payload length is not 12 bytes.

    """
    if len(payload) != 12:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_SYSTEM_TIME,
            reason=f"expected 12 bytes, got {len(payload)}",
        )
    unix_usec, boot_ms = struct.unpack("<QI", payload)
    return SystemTime(unix_usec=unix_usec, boot_ms=boot_ms)


def encode_soft_reboot(camera: bool, gimbal: bool) -> bytes:
    """Encode soft reboot request (0x80).

    Args:
        camera: True to reboot camera.
        gimbal: True to reset gimbal.

    Returns:
        2-byte payload.

    """
    return struct.pack("<BB", int(camera), int(gimbal))


def decode_soft_reboot_ack(payload: bytes) -> tuple[bool, bool]:
    """Decode soft reboot acknowledgment (0x80).

    Args:
        payload: 2-byte acknowledgment.

    Returns:
        Tuple of (camera_rebooted, gimbal_reset).

    Raises:
        MalformedPayloadError: If payload length is not 2 bytes.

    """
    if len(payload) != 2:
        raise MalformedPayloadError(
            cmd_id=CMD_SOFT_REBOOT,
            reason=f"expected 2 bytes, got {len(payload)}",
        )
    camera_byte, gimbal_byte = struct.unpack("<BB", payload)
    return (bool(camera_byte), bool(gimbal_byte))


def encode_get_ip() -> bytes:
    """Encode get IP configuration request (0x81).

    Returns:
        Empty payload.

    """
    return b""


def decode_get_ip(payload: bytes) -> IPConfig:
    """Decode get IP configuration response (0x81).

    Args:
        payload: 12 bytes (3 x uint32 LE → IPv4 addresses).

    Returns:
        IPConfig dataclass.

    Raises:
        MalformedPayloadError: If payload length is not 12 bytes.

    """
    if len(payload) != 12:
        raise MalformedPayloadError(
            cmd_id=CMD_GET_IP,
            reason=f"expected 12 bytes, got {len(payload)}",
        )
    ip_int, mask_int, gw_int = struct.unpack("<III", payload)
    # Convert uint32 to IPv4Address
    return IPConfig(
        ip=IPv4Address(ip_int),
        mask=IPv4Address(mask_int),
        gateway=IPv4Address(gw_int),
    )


def encode_set_ip(cfg: IPConfig) -> bytes:
    """Encode set IP configuration request (0x82).

    Args:
        cfg: IP configuration to set.

    Returns:
        12-byte payload (3 x uint32 LE).

    """
    # IPv4Address can be converted to int directly
    ip_int = int(cfg.ip)
    mask_int = int(cfg.mask)
    gw_int = int(cfg.gateway)
    return struct.pack("<III", ip_int, mask_int, gw_int)


def decode_set_ip_ack(payload: bytes) -> None:
    """Decode set IP configuration acknowledgment (0x82).

    Args:
        payload: 1-byte acknowledgment.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.
        ResponseError: If acknowledgment is 0 (failure).

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_IP,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (ack,) = struct.unpack("<B", payload)
    if ack == 0:
        raise ResponseError(cmd_id=CMD_SET_IP, sta=ack)
