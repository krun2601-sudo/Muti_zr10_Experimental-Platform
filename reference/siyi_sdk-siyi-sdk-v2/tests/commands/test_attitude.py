# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for attitude command encoders and decoders."""

import struct

import pytest

from siyi_sdk.commands.attitude import (
    decode_fc_stream_ack,
    decode_gimbal_attitude,
    decode_gimbal_stream_ack,
    decode_magnetic_encoder,
    encode_aircraft_attitude,
    encode_fc_stream,
    encode_gimbal_attitude,
    encode_gimbal_stream,
    encode_magnetic_encoder,
    encode_raw_gps,
)
from siyi_sdk.exceptions import MalformedPayloadError
from siyi_sdk.models import (
    AircraftAttitude,
    DataStreamFreq,
    FCDataType,
    GimbalDataType,
    RawGPS,
)


class TestGimbalAttitude:
    def test_encode(self):
        assert encode_gimbal_attitude() == b""

    def test_decode(self):
        # yaw=100, pitch=-50, roll=20, all rates=0 (all in deciDeg)
        payload = struct.pack("<hhhhhh", 1000, -500, 200, 0, 0, 0)
        result = decode_gimbal_attitude(payload)
        assert result.yaw_deg == 100.0
        assert result.pitch_deg == -50.0
        assert result.roll_deg == 20.0
        assert result.yaw_rate_dps == 0.0

    def test_decode_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_gimbal_attitude(b"\x00" * 11)


class TestAircraftAttitude:
    def test_encode(self):
        att = AircraftAttitude(
            time_boot_ms=1000,
            roll_rad=0.1,
            pitch_rad=-0.2,
            yaw_rad=1.5,
            rollspeed=0.01,
            pitchspeed=-0.02,
            yawspeed=0.03,
        )
        payload = encode_aircraft_attitude(att)
        assert len(payload) == 28

    def test_round_trip(self):
        att = AircraftAttitude(
            time_boot_ms=123456,
            roll_rad=0.5,
            pitch_rad=-0.3,
            yaw_rad=2.1,
            rollspeed=0.1,
            pitchspeed=0.2,
            yawspeed=0.3,
        )
        payload = encode_aircraft_attitude(att)
        unpacked = struct.unpack("<Iffffff", payload)
        assert unpacked[0] == att.time_boot_ms
        assert abs(unpacked[1] - att.roll_rad) < 0.0001


class TestFCStream:
    def test_encode(self):
        payload = encode_fc_stream(FCDataType.ATTITUDE, DataStreamFreq.HZ10)
        assert payload == b"\x01\x04"

    def test_decode_ack(self):
        result = decode_fc_stream_ack(b"\x01")
        assert result == FCDataType.ATTITUDE

    def test_decode_ack_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_fc_stream_ack(b"")


class TestGimbalStream:
    def test_encode(self):
        payload = encode_gimbal_stream(GimbalDataType.LASER_RANGE, DataStreamFreq.OFF)
        assert payload == b"\x02\x00"

    def test_decode_ack(self):
        result = decode_gimbal_stream_ack(b"\x03")
        assert result == GimbalDataType.MAGNETIC_ENCODER


class TestMagneticEncoder:
    def test_encode(self):
        assert encode_magnetic_encoder() == b""

    def test_decode(self):
        payload = struct.pack("<hhh", 450, -300, 100)
        result = decode_magnetic_encoder(payload)
        assert result.yaw == 45.0
        assert result.pitch == -30.0
        assert result.roll == 10.0

    def test_decode_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_magnetic_encoder(b"\x00" * 5)


class TestRawGPS:
    def test_encode(self):
        gps = RawGPS(
            time_boot_ms=1000,
            lat_e7=473977418,  # 47.3977418°
            lon_e7=85239505,  # 8.5239505°
            alt_msl_cm=43000,
            alt_ellipsoid_cm=43500,
            vn_mmps=1000,
            ve_mmps=500,
            vd_mmps=-100,
        )
        payload = encode_raw_gps(gps)
        assert len(payload) == 32

    def test_round_trip(self):
        gps = RawGPS(
            time_boot_ms=2000,
            lat_e7=400000000,
            lon_e7=-750000000,
            alt_msl_cm=50000,
            alt_ellipsoid_cm=50500,
            vn_mmps=2000,
            ve_mmps=-1000,
            vd_mmps=500,
        )
        payload = encode_raw_gps(gps)
        unpacked = struct.unpack("<Iiiiiiii", payload)
        assert unpacked[0] == gps.time_boot_ms
        assert unpacked[1] == gps.lat_e7
        assert unpacked[2] == gps.lon_e7
