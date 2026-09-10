# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for RC, debug, and AI command encoders and decoders."""

import struct

import pytest

from siyi_sdk.commands.ai import (
    decode_ai_mode,
    decode_ai_tracking,
    decode_set_ai_stream_output_ack,
    encode_get_ai_mode,
    encode_set_ai_stream_output,
)
from siyi_sdk.commands.debug import (
    decode_motor_voltage,
    decode_weak_threshold,
    encode_get_motor_voltage,
    encode_get_weak_threshold,
    encode_set_weak_threshold,
)
from siyi_sdk.commands.rc import decode_rc_channels, encode_rc_channels
from siyi_sdk.exceptions import ConfigurationError, ResponseError
from siyi_sdk.models import (
    AITargetID,
    AITrackStatus,
    RCChannels,
    WeakControlThreshold,
)


class TestRCChannels:
    def test_encode(self):
        ch = RCChannels(
            chans=tuple(range(1000, 2800, 100)),  # 18 channels
            chancount=18,
            rssi=200,
        )
        payload = encode_rc_channels(ch)
        assert len(payload) == 38  # 18*2 + 1 + 1

    def test_encode_invalid_count(self):
        ch = RCChannels(chans=tuple(range(10)), chancount=10, rssi=100)
        with pytest.raises(ConfigurationError):
            encode_rc_channels(ch)

    def test_decode(self):
        # Create payload: 18 channels + chancount + rssi
        chans = tuple(range(1000, 2800, 100))
        payload = struct.pack("<18HBB", *chans, 18, 200)
        result = decode_rc_channels(payload)
        assert result.chans == chans
        assert result.chancount == 18
        assert result.rssi == 200

    def test_round_trip(self):
        ch = RCChannels(
            chans=tuple([1500] * 18),
            chancount=18,
            rssi=255,
        )
        payload = encode_rc_channels(ch)
        decoded = decode_rc_channels(payload)
        assert decoded.chans == ch.chans
        assert decoded.chancount == ch.chancount
        assert decoded.rssi == ch.rssi


class TestMotorVoltage:
    def test_encode(self):
        assert encode_get_motor_voltage() == b""

    def test_decode(self):
        # yaw=5000 (5.0V), pitch=-3000 (-3.0V), roll=12000 (12.0V)
        payload = struct.pack("<hhh", 5000, -3000, 12000)
        result = decode_motor_voltage(payload)
        assert result.yaw == 5.0
        assert result.pitch == -3.0
        assert result.roll == 12.0


class TestWeakThreshold:
    def test_encode_get(self):
        assert encode_get_weak_threshold() == b""

    def test_decode(self):
        # limit=30 (3.0), voltage=40 (4.0), angular_error=100 (10.0)
        payload = struct.pack("<hhh", 30, 40, 100)
        result = decode_weak_threshold(payload)
        assert result.limit == 3.0
        assert result.voltage == 4.0
        assert result.angular_error == 10.0

    def test_encode_set(self):
        t = WeakControlThreshold(limit=2.5, voltage=3.5, angular_error=15.0)
        payload = encode_set_weak_threshold(t)
        assert len(payload) == 6

    def test_round_trip(self):
        t = WeakControlThreshold(limit=3.5, voltage=4.5, angular_error=20.5)
        payload = encode_set_weak_threshold(t)
        decoded = decode_weak_threshold(payload)
        assert decoded.limit == t.limit
        assert decoded.voltage == t.voltage
        assert decoded.angular_error == t.angular_error


class TestAIMode:
    def test_encode(self):
        assert encode_get_ai_mode() == b""

    def test_decode(self):
        assert decode_ai_mode(b"\x00") is False
        assert decode_ai_mode(b"\x01") is True


class TestAITracking:
    def test_decode(self):
        # x=640, y=360, w=100, h=80, target=CAR, status=NORMAL_AI
        payload = struct.pack("<HHHHBB", 640, 360, 100, 80, 1, 0)
        result = decode_ai_tracking(payload)
        assert result.x == 640
        assert result.y == 360
        assert result.w == 100
        assert result.h == 80
        assert result.target_id == AITargetID.CAR
        assert result.status == AITrackStatus.NORMAL_AI

    def test_decode_any_target(self):
        payload = struct.pack("<HHHHBB", 320, 240, 50, 50, 255, 0)
        result = decode_ai_tracking(payload)
        assert result.target_id == AITargetID.ANY
        assert result.target_id.name == "ANY"


class TestAIStreamOutput:
    def test_encode(self):
        assert encode_set_ai_stream_output(True) == b"\x01"
        assert encode_set_ai_stream_output(False) == b"\x00"

    def test_decode_ack_success(self):
        assert decode_set_ai_stream_output_ack(b"\x01") is True

    def test_decode_ack_failure(self):
        with pytest.raises(ResponseError):
            decode_set_ai_stream_output_ack(b"\x00")
