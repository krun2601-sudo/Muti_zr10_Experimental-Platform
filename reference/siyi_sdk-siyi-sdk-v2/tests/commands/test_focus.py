# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for focus command encoders and decoders."""

import pytest

from siyi_sdk.commands.focus import (
    decode_auto_focus_ack,
    decode_manual_focus_ack,
    encode_auto_focus,
    encode_manual_focus,
)
from siyi_sdk.exceptions import ConfigurationError, MalformedPayloadError, ResponseError


class TestAutoFocus:
    def test_encode_chapter4_example(self):
        # Chapter 4 example: auto_focus(1, 300, 100) → 01 2C 01 64 00
        payload = encode_auto_focus(1, 300, 100)
        assert payload == bytes.fromhex("01 2C 01 64 00")

    def test_encode_valid(self):
        payload = encode_auto_focus(0, 0, 0)
        assert len(payload) == 5

        payload = encode_auto_focus(255, 65535, 65535)
        assert len(payload) == 5

    def test_encode_out_of_range(self):
        with pytest.raises(ConfigurationError):
            encode_auto_focus(-1, 100, 100)

        with pytest.raises(ConfigurationError):
            encode_auto_focus(256, 100, 100)

        with pytest.raises(ConfigurationError):
            encode_auto_focus(1, -1, 100)

        with pytest.raises(ConfigurationError):
            encode_auto_focus(1, 100, 65536)

    def test_decode_ack_success(self):
        decode_auto_focus_ack(b"\x01")  # Should not raise

    def test_decode_ack_failure(self):
        with pytest.raises(ResponseError):
            decode_auto_focus_ack(b"\x00")

    def test_decode_ack_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_auto_focus_ack(b"\x01\x00")


class TestManualFocus:
    def test_encode_valid(self):
        assert encode_manual_focus(-1) == b"\xff"
        assert encode_manual_focus(0) == b"\x00"
        assert encode_manual_focus(1) == b"\x01"

    def test_encode_invalid(self):
        with pytest.raises(ConfigurationError):
            encode_manual_focus(-2)

        with pytest.raises(ConfigurationError):
            encode_manual_focus(2)

    def test_decode_ack_success(self):
        decode_manual_focus_ack(b"\x01")  # Should not raise

    def test_decode_ack_failure(self):
        with pytest.raises(ResponseError):
            decode_manual_focus_ack(b"\x00")

    def test_decode_ack_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_manual_focus_ack(b"")
