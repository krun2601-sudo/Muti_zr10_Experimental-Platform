# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for gimbal command encoders and decoders."""

import pytest

from siyi_sdk.commands.gimbal import (
    decode_gimbal_mode,
    decode_one_key_centering_ack,
    decode_rotation_ack,
    decode_set_attitude_ack,
    decode_single_axis_ack,
    encode_gimbal_mode,
    encode_one_key_centering,
    encode_rotation,
    encode_set_attitude,
    encode_single_axis,
)
from siyi_sdk.exceptions import ConfigurationError, MalformedPayloadError, ResponseError
from siyi_sdk.models import CenteringAction, GimbalMotionMode


class TestRotation:
    def test_encode_chapter4_example(self):
        # Chapter 4 example: rotate(100, 100) → 64 64
        payload = encode_rotation(100, 100)
        assert payload == bytes.fromhex("64 64")

    def test_encode_valid(self):
        assert encode_rotation(-100, -100) == b"\x9c\x9c"
        assert encode_rotation(0, 0) == b"\x00\x00"
        assert encode_rotation(50, -50) == b"\x32\xce"

    def test_encode_out_of_range(self):
        with pytest.raises(ConfigurationError):
            encode_rotation(-101, 0)

        with pytest.raises(ConfigurationError):
            encode_rotation(0, 101)

    def test_decode_ack_success(self):
        decode_rotation_ack(b"\x01")  # Should not raise

    def test_decode_ack_failure(self):
        with pytest.raises(ResponseError):
            decode_rotation_ack(b"\x00")

    def test_decode_ack_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_rotation_ack(b"")


class TestOneKeyCentering:
    def test_encode_valid(self):
        assert encode_one_key_centering(CenteringAction.ONE_KEY_CENTER) == b"\x01"
        assert encode_one_key_centering(CenteringAction.CENTER_DOWNWARD) == b"\x02"
        assert encode_one_key_centering(CenteringAction.CENTER) == b"\x03"
        assert encode_one_key_centering(CenteringAction.DOWNWARD) == b"\x04"

    def test_encode_invalid(self):
        with pytest.raises(ConfigurationError):
            encode_one_key_centering(5)

    def test_decode_ack_success(self):
        decode_one_key_centering_ack(b"\x01")  # Should not raise

    def test_decode_ack_failure(self):
        with pytest.raises(ResponseError):
            decode_one_key_centering_ack(b"\x00")


class TestSetAttitude:
    def test_encode_chapter4_example(self):
        # Chapter 4 example: set_attitude(-90.0, 0.0)
        # yaw = -90.0 → -900 deciDeg → 0xFC7C little-endian
        # pitch = 0.0 → 0 → 0x0000
        payload = encode_set_attitude(-90.0, 0.0)
        assert payload == bytes.fromhex("7C FC 00 00")

    def test_encode_valid(self):
        # Zero angles
        payload = encode_set_attitude(0.0, 0.0)
        assert payload == b"\x00\x00\x00\x00"

        # Positive angles
        payload = encode_set_attitude(45.0, 25.0)
        # 45.0 * 10 = 450 = 0x01C2
        # 25.0 * 10 = 250 = 0x00FA
        assert payload == bytes.fromhex("C2 01 FA 00")

    def test_decode_ack(self):
        # yaw=100, pitch=-50, roll=0 (all in deciDeg)
        payload = bytes.fromhex("E8 03 CE FF 00 00")
        result = decode_set_attitude_ack(payload)
        assert result.yaw_deg == 100.0
        assert result.pitch_deg == -5.0
        assert result.roll_deg == 0.0

    def test_decode_ack_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_set_attitude_ack(b"\x00" * 5)


class TestGimbalMode:
    def test_encode(self):
        assert encode_gimbal_mode() == b""

    def test_decode(self):
        assert decode_gimbal_mode(b"\x00") == GimbalMotionMode.LOCK
        assert decode_gimbal_mode(b"\x01") == GimbalMotionMode.FOLLOW
        assert decode_gimbal_mode(b"\x02") == GimbalMotionMode.FPV

    def test_decode_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_gimbal_mode(b"")


class TestSingleAxis:
    def test_encode_valid(self):
        # Yaw axis, 45 degrees
        payload = encode_single_axis(45.0, 0)
        # 45.0 * 10 = 450 = 0x01C2, axis = 0
        assert payload == bytes.fromhex("C2 01 00")

        # Pitch axis, -30 degrees
        payload = encode_single_axis(-30.0, 1)
        # -30.0 * 10 = -300 = 0xFED4, axis = 1
        assert payload == bytes.fromhex("D4 FE 01")

    def test_encode_invalid_axis(self):
        with pytest.raises(ConfigurationError):
            encode_single_axis(0.0, 2)

    def test_decode_ack(self):
        # Same format as set_attitude_ack
        payload = bytes.fromhex("00 00 FA 00 00 00")
        result = decode_single_axis_ack(payload)
        assert result.yaw_deg == 0.0
        assert result.pitch_deg == 25.0
        assert result.roll_deg == 0.0

    def test_decode_ack_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_single_axis_ack(b"\x00" * 4)
