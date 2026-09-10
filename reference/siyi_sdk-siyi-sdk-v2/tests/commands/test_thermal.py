# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for thermal command encoders and decoders."""

from siyi_sdk.commands.thermal import (
    decode_pseudo_color,
    decode_set_pseudo_color_ack,
    decode_set_thermal_gain_ack,
    decode_temp_at_point,
    decode_thermal_gain,
    encode_get_pseudo_color,
    encode_get_thermal_gain,
    encode_set_pseudo_color,
    encode_set_thermal_gain,
    encode_temp_at_point,
)
from siyi_sdk.models import PseudoColor, TempMeasureFlag, ThermalGain


class TestTempAtPoint:
    def test_encode(self):
        payload = encode_temp_at_point(100, 200, TempMeasureFlag.MEASURE_ONCE)
        assert len(payload) == 5

    def test_decode(self):
        # temp_raw=3000 (30.00°C), x=100, y=200
        payload = b"\xb8\x0b\x64\x00\xc8\x00"
        result = decode_temp_at_point(payload)
        assert result.temperature_c == 30.0
        assert result.x == 100
        assert result.y == 200


class TestPseudoColor:
    def test_encode_get(self):
        assert encode_get_pseudo_color() == b""

    def test_encode_set(self):
        payload = encode_set_pseudo_color(PseudoColor.WHITE_HOT)
        assert payload == b"\x00"

        payload = encode_set_pseudo_color(PseudoColor.IRONBOW)
        assert payload == b"\x03"

    def test_decode(self):
        assert decode_pseudo_color(b"\x00") == PseudoColor.WHITE_HOT
        assert decode_pseudo_color(b"\x0b") == PseudoColor.GLORY_HOT

    def test_decode_ack(self):
        result = decode_set_pseudo_color_ack(b"\x04")
        assert result == PseudoColor.RAINBOW

    def test_round_trip_all_colors(self):
        for color in PseudoColor:
            if color == PseudoColor.RESERVED:
                continue
            payload = encode_set_pseudo_color(color)
            decoded = decode_set_pseudo_color_ack(payload)
            assert decoded == color


class TestThermalGain:
    def test_encode_get(self):
        assert encode_get_thermal_gain() == b""

    def test_encode_set(self):
        assert encode_set_thermal_gain(ThermalGain.LOW) == b"\x00"
        assert encode_set_thermal_gain(ThermalGain.HIGH) == b"\x01"

    def test_decode(self):
        assert decode_thermal_gain(b"\x00") == ThermalGain.LOW
        assert decode_thermal_gain(b"\x01") == ThermalGain.HIGH

    def test_decode_ack(self):
        assert decode_set_thermal_gain_ack(b"\x01") == ThermalGain.HIGH

    def test_round_trip(self):
        for gain in ThermalGain:
            payload = encode_set_thermal_gain(gain)
            decoded = decode_set_thermal_gain_ack(payload)
            assert decoded == gain
