# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for zoom command encoders and decoders."""

import pytest

from siyi_sdk.commands.zoom import (
    decode_absolute_zoom_ack,
    decode_current_zoom,
    decode_manual_zoom_ack,
    decode_zoom_range,
    encode_absolute_zoom,
    encode_current_zoom,
    encode_manual_zoom,
    encode_zoom_range,
)
from siyi_sdk.exceptions import ConfigurationError, MalformedPayloadError, ResponseError
from siyi_sdk.models import CurrentZoom


class TestManualZoom:
    def test_encode_valid(self):
        assert encode_manual_zoom(-1) == b"\xff"
        assert encode_manual_zoom(0) == b"\x00"
        assert encode_manual_zoom(1) == b"\x01"

    def test_encode_invalid(self):
        with pytest.raises(ConfigurationError):
            encode_manual_zoom(-2)

        with pytest.raises(ConfigurationError):
            encode_manual_zoom(2)

    def test_decode_ack(self):
        # Raw value 100 → 10.0x zoom
        result = decode_manual_zoom_ack(b"\x64\x00")
        assert result == 10.0

        # Raw value 50 → 5.0x zoom
        result = decode_manual_zoom_ack(b"\x32\x00")
        assert result == 5.0

    def test_decode_ack_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_manual_zoom_ack(b"\x64")


class TestAbsoluteZoom:
    def test_encode_chapter4_example(self):
        # Chapter 4 example: absolute_zoom(4.5) → 04 05
        payload = encode_absolute_zoom(4.5)
        assert payload == bytes.fromhex("04 05")

    def test_encode_valid(self):
        assert encode_absolute_zoom(1.0) == b"\x01\x00"
        assert encode_absolute_zoom(10.5) == b"\x0a\x05"
        assert encode_absolute_zoom(30.0) == b"\x1e\x00"

    def test_encode_rounding(self):
        # 4.95 should round to 5.0 (int=5, float=0)
        payload = encode_absolute_zoom(4.95)
        assert payload == b"\x05\x00"

        # 4.94 should round to 4.9
        payload = encode_absolute_zoom(4.94)
        assert payload == b"\x04\x09"

    def test_encode_out_of_range(self):
        with pytest.raises(ConfigurationError):
            encode_absolute_zoom(0.5)

        with pytest.raises(ConfigurationError):
            encode_absolute_zoom(30.1)

    def test_decode_ack_success(self):
        decode_absolute_zoom_ack(b"\x01")  # Should not raise

    def test_decode_ack_failure(self):
        with pytest.raises(ResponseError):
            decode_absolute_zoom_ack(b"\x00")

    def test_decode_ack_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_absolute_zoom_ack(b"")


class TestZoomRange:
    def test_encode(self):
        assert encode_zoom_range() == b""

    def test_decode(self):
        # Max zoom 30.5
        payload = b"\x1e\x05"
        result = decode_zoom_range(payload)
        assert result.max_int == 30
        assert result.max_float == 5
        assert result.max_zoom == 30.5

    def test_decode_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_zoom_range(b"\x1e")


class TestCurrentZoom:
    def test_encode(self):
        assert encode_current_zoom() == b""

    def test_decode_chapter4_example(self):
        # Current zoom 1.0
        payload = b"\x01\x00"
        result = decode_current_zoom(payload)
        assert result.integer == 1
        assert result.decimal == 0
        assert result.zoom == 1.0

    def test_decode(self):
        # Current zoom 5.3
        payload = b"\x05\x03"
        result = decode_current_zoom(payload)
        assert result.integer == 5
        assert result.decimal == 3
        assert result.zoom == 5.3

    def test_decode_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_current_zoom(b"\x05")

    def test_round_trip(self):
        # Encode then decode via models
        zoom_val = 12.7
        int_part = int(zoom_val)
        float_part = round((zoom_val - int_part) * 10)
        zoom_obj = CurrentZoom(integer=int_part, decimal=float_part)
        assert zoom_obj.zoom == 12.7
