# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for camera and video command encoders and decoders."""

import pytest

from siyi_sdk.commands.camera import (
    decode_set_encoding_params_ack,
    encode_capture,
    encode_get_encoding_params,
    encode_set_encoding_params,
)
from siyi_sdk.commands.video import (
    decode_set_video_stitching_mode_ack,
    decode_video_stitching_mode,
    encode_get_video_stitching_mode,
    encode_set_video_stitching_mode,
)
from siyi_sdk.exceptions import ConfigurationError, ResponseError
from siyi_sdk.models import (
    CaptureFuncType,
    EncodingParams,
    StreamType,
    VideoEncType,
    VideoStitchingMode,
)


class TestCapture:
    def test_encode(self):
        payload = encode_capture(CaptureFuncType.PHOTO)
        assert payload == b"\x00"

        payload = encode_capture(CaptureFuncType.START_RECORD)
        assert payload == b"\x02"


class TestEncodingParams:
    def test_encode_get(self):
        payload = encode_get_encoding_params(StreamType.MAIN)
        assert payload == b"\x01"

    def test_encode_set_valid(self):
        params = EncodingParams(
            stream_type=StreamType.MAIN,
            enc_type=VideoEncType.H265,
            resolution_w=1920,
            resolution_h=1080,
            bitrate_kbps=1500,
            frame_rate=30,
        )
        payload = encode_set_encoding_params(params)
        assert len(payload) == 9

    def test_encode_set_invalid_resolution(self):
        params = EncodingParams(
            stream_type=StreamType.MAIN,
            enc_type=VideoEncType.H265,
            resolution_w=1280,
            resolution_h=960,  # Invalid
            bitrate_kbps=1500,
            frame_rate=30,
        )
        with pytest.raises(ConfigurationError):
            encode_set_encoding_params(params)

    def test_decode_set_ack_success(self):
        assert decode_set_encoding_params_ack(b"\x01\x01") is True

    def test_decode_set_ack_failure(self):
        with pytest.raises(ResponseError):
            decode_set_encoding_params_ack(b"\x01\x00")


class TestVideoStitching:
    def test_encode_get(self):
        assert encode_get_video_stitching_mode() == b""

    def test_encode_set(self):
        payload = encode_set_video_stitching_mode(VideoStitchingMode.MODE_0)
        assert payload == b"\x00"

    def test_decode(self):
        for i in range(9):
            result = decode_video_stitching_mode(bytes([i]))
            assert result == VideoStitchingMode(i)

    def test_decode_ack(self):
        result = decode_set_video_stitching_mode_ack(b"\x05")
        assert result == VideoStitchingMode.MODE_5

    def test_round_trip_all_modes(self):
        for mode in VideoStitchingMode:
            payload = encode_set_video_stitching_mode(mode)
            decoded = decode_set_video_stitching_mode_ack(payload)
            assert decoded == mode
