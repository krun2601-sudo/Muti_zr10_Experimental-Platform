# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for laser command encoders and decoders."""

import pytest

from siyi_sdk.commands.laser import (
    decode_laser_distance,
    decode_laser_target_latlon,
    decode_set_laser_ranging_state_ack,
    encode_laser_distance,
    encode_laser_target_latlon,
    encode_set_laser_ranging_state,
)
from siyi_sdk.exceptions import MalformedPayloadError, ResponseError


class TestLaserDistance:
    def test_encode(self):
        assert encode_laser_distance() == b""

    def test_decode_valid(self):
        # raw=100 → 10.0 m
        result = decode_laser_distance(b"\x64\x00")
        assert result.distance_m == 10.0

        # raw=50 → 5.0 m (minimum valid)
        result = decode_laser_distance(b"\x32\x00")
        assert result.distance_m == 5.0

        # raw=12000 → 1200.0 m
        result = decode_laser_distance(b"\xe0\x2e")
        assert result.distance_m == 1200.0

    def test_decode_out_of_range(self):
        # raw=0 → None
        result = decode_laser_distance(b"\x00\x00")
        assert result.distance_m is None

        # raw=49 (< 50) → None
        result = decode_laser_distance(b"\x31\x00")
        assert result.distance_m is None

    def test_decode_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_laser_distance(b"\x64")


class TestLaserTargetLatLon:
    def test_encode(self):
        assert encode_laser_target_latlon() == b""

    def test_decode(self):
        # lon=85239505 (8.5239505°E), lat=473977418 (47.3977418°N)
        # Encoded as: lon (int32 LE), lat (int32 LE)
        import struct

        payload = struct.pack("<ii", 85239505, 473977418)
        result = decode_laser_target_latlon(payload)
        assert result.lon_e7 == 85239505
        assert result.lat_e7 == 473977418

    def test_decode_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_laser_target_latlon(b"\x00" * 7)


class TestSetLaserRangingState:
    def test_encode(self):
        assert encode_set_laser_ranging_state(True) == b"\x01"
        assert encode_set_laser_ranging_state(False) == b"\x00"

    def test_decode_ack_success(self):
        assert decode_set_laser_ranging_state_ack(b"\x01") is True

    def test_decode_ack_failure(self):
        with pytest.raises(ResponseError):
            decode_set_laser_ranging_state_ack(b"\x00")
