# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Extended tests for debug commands."""

import pytest

from siyi_sdk.commands.debug import (
    decode_control_mode,
    decode_set_weak_control_mode_ack,
    decode_weak_control_mode,
    encode_get_control_mode,
    encode_get_weak_control_mode,
    encode_set_weak_control_mode,
)
from siyi_sdk.exceptions import MalformedPayloadError, ResponseError
from siyi_sdk.models import ControlMode


class TestControlMode:
    def test_encode(self):
        assert encode_get_control_mode() == b""

    def test_decode_all(self):
        for i in range(5):
            result = decode_control_mode(bytes([i]))
            assert result == ControlMode(i)

    def test_decode_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_control_mode(b"")


class TestWeakControlMode:
    def test_encode_get(self):
        assert encode_get_weak_control_mode() == b""

    def test_decode_get(self):
        assert decode_weak_control_mode(b"\x00") is False
        assert decode_weak_control_mode(b"\x01") is True

    def test_decode_get_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_weak_control_mode(b"")

    def test_encode_set(self):
        assert encode_set_weak_control_mode(True) == b"\x01"
        assert encode_set_weak_control_mode(False) == b"\x00"

    def test_decode_set_ack_success(self):
        assert decode_set_weak_control_mode_ack(b"\x01\x01") is True
        assert decode_set_weak_control_mode_ack(b"\x01\x00") is False

    def test_decode_set_ack_failure(self):
        with pytest.raises(ResponseError):
            decode_set_weak_control_mode_ack(b"\x00\x01")

    def test_decode_set_ack_wrong_length(self):
        with pytest.raises(MalformedPayloadError):
            decode_set_weak_control_mode_ack(b"\x01")
