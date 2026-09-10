# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for system command encoders and decoders."""

from ipaddress import IPv4Address

import pytest

from siyi_sdk.commands.system import (
    decode_firmware_version,
    decode_get_ip,
    decode_gimbal_system_info,
    decode_hardware_id,
    decode_set_ip_ack,
    decode_set_utc_time_ack,
    decode_soft_reboot_ack,
    decode_system_time,
    encode_firmware_version,
    encode_get_ip,
    encode_gimbal_system_info,
    encode_hardware_id,
    encode_heartbeat,
    encode_set_ip,
    encode_set_utc_time,
    encode_soft_reboot,
    encode_system_time,
)
from siyi_sdk.exceptions import ConfigurationError, MalformedPayloadError, ResponseError
from siyi_sdk.models import FirmwareVersion, IPConfig


class TestHeartbeat:
    def test_encode(self):
        assert encode_heartbeat() == b""


class TestFirmwareVersion:
    def test_encode(self):
        assert encode_firmware_version() == b""

    def test_decode(self):
        # Example: camera, gimbal, zoom as uint32 LE
        import struct

        payload = struct.pack("<III", 0x06030203, 0x01020304, 0x05060708)
        result = decode_firmware_version(payload)
        assert result.camera == 0x06030203
        assert result.gimbal == 0x01020304
        assert result.zoom == 0x05060708

    def test_decode_firmware_word(self):
        # Per spec: 0x6E030203 → major=3, minor=2, patch=3
        word = 0x6E030203
        major, minor, patch = FirmwareVersion.decode_word(word)
        assert major == 3
        assert minor == 2
        assert patch == 3

    def test_decode_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_firmware_version(b"\x00" * 11)


class TestHardwareID:
    def test_encode(self):
        assert encode_hardware_id() == b""

    def test_decode(self):
        payload = b"\x6b" + b"\x00" * 11
        result = decode_hardware_id(payload)
        assert result.raw == payload
        assert len(result.raw) == 12

    def test_decode_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_hardware_id(b"\x00" * 10)


class TestSetUTCTime:
    def test_encode(self):
        unix_usec = 1609459200000000  # 2021-01-01 00:00:00 UTC
        payload = encode_set_utc_time(unix_usec)
        assert len(payload) == 8

    def test_encode_negative(self):
        with pytest.raises(ConfigurationError):
            encode_set_utc_time(-1)

    def test_decode_ack_success(self):
        assert decode_set_utc_time_ack(b"\x01") is True

    def test_decode_ack_failure(self):
        with pytest.raises(ResponseError):
            decode_set_utc_time_ack(b"\x00")

    def test_decode_ack_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_set_utc_time_ack(b"\x01\x00")


class TestGimbalSystemInfo:
    def test_encode(self):
        assert encode_gimbal_system_info() == b""

    def test_decode(self):
        payload = b"\x01"
        result = decode_gimbal_system_info(payload)
        assert result.laser_state is True

        payload = b"\x00"
        result = decode_gimbal_system_info(payload)
        assert result.laser_state is False

    def test_decode_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_gimbal_system_info(b"\x01\x00")


class TestSystemTime:
    def test_encode(self):
        assert encode_system_time() == b""

    def test_decode(self):
        unix_usec = 1609459200000000
        boot_ms = 123456
        payload = unix_usec.to_bytes(8, "little") + boot_ms.to_bytes(4, "little")
        result = decode_system_time(payload)
        assert result.unix_usec == unix_usec
        assert result.boot_ms == boot_ms

    def test_decode_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_system_time(b"\x00" * 11)


class TestSoftReboot:
    def test_encode(self):
        payload = encode_soft_reboot(True, False)
        assert payload == b"\x01\x00"

        payload = encode_soft_reboot(False, True)
        assert payload == b"\x00\x01"

    def test_decode_ack(self):
        camera, gimbal = decode_soft_reboot_ack(b"\x01\x00")
        assert camera is True
        assert gimbal is False

    def test_decode_ack_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_soft_reboot_ack(b"\x01")


class TestIPConfig:
    def test_encode_get(self):
        assert encode_get_ip() == b""

    def test_decode_get(self):
        # IP: 192.168.144.25 = 0xC0A89019
        # Mask: 255.255.255.0 = 0xFFFFFF00
        # GW: 192.168.144.1 = 0xC0A89001
        payload = bytes.fromhex("1990A8C0 00FFFFFF 0190A8C0")
        result = decode_get_ip(payload)
        assert result.ip == IPv4Address("192.168.144.25")
        assert result.mask == IPv4Address("255.255.255.0")
        assert result.gateway == IPv4Address("192.168.144.1")

    def test_decode_get_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_get_ip(b"\x00" * 10)

    def test_encode_set(self):
        cfg = IPConfig(
            ip=IPv4Address("192.168.1.100"),
            mask=IPv4Address("255.255.255.0"),
            gateway=IPv4Address("192.168.1.1"),
        )
        payload = encode_set_ip(cfg)
        assert len(payload) == 12

    def test_decode_set_ack_success(self):
        decode_set_ip_ack(b"\x01")  # Should not raise

    def test_decode_set_ack_failure(self):
        with pytest.raises(ResponseError):
            decode_set_ip_ack(b"\x00")

    def test_decode_set_ack_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_set_ip_ack(b"\x01\x00")

    def test_round_trip(self):
        cfg = IPConfig(
            ip=IPv4Address("10.0.0.1"),
            mask=IPv4Address("255.255.0.0"),
            gateway=IPv4Address("10.0.0.254"),
        )
        payload = encode_set_ip(cfg)
        decoded = decode_get_ip(payload)
        assert decoded.ip == cfg.ip
        assert decoded.mask == cfg.mask
        assert decoded.gateway == cfg.gateway
