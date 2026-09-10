# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Extended tests for camera commands."""

import pytest

from siyi_sdk.commands.camera import (
    decode_camera_system_info,
    decode_format_sd_ack,
    decode_function_feedback,
    decode_get_osd_flag,
    decode_get_pic_name_type,
    decode_set_osd_flag_ack,
    decode_set_pic_name_type_ack,
    encode_camera_system_info,
    encode_format_sd,
    encode_get_osd_flag,
    encode_get_pic_name_type,
    encode_set_osd_flag,
    encode_set_pic_name_type,
)
from siyi_sdk.exceptions import ResponseError
from siyi_sdk.models import (
    FileNameType,
    FileType,
    FunctionFeedback,
    GimbalMotionMode,
    HDMICVBSOutput,
    MountingDirection,
    RecordingState,
)


class TestCameraSystemInfo:
    def test_encode(self):
        assert encode_camera_system_info() == b""

    def test_decode(self):
        # reserved_a, hdr_sta, reserved_b, record_sta, motion, mount, hdmi, zoom_link
        payload = b"\x00\x01\x00\x01\x01\x01\x00\x01"
        result = decode_camera_system_info(payload)
        assert result.hdr_sta == 1
        assert result.record_sta == RecordingState.RECORDING
        assert result.gimbal_motion_mode == GimbalMotionMode.FOLLOW
        assert result.gimbal_mounting_dir == MountingDirection.NORMAL
        assert result.video_hdmi_or_cvbs == HDMICVBSOutput.HDMI_ON_CVBS_OFF
        assert result.zoom_linkage == 1


class TestFunctionFeedback:
    def test_decode_all(self):
        for i in range(7):
            result = decode_function_feedback(bytes([i]))
            assert result == FunctionFeedback(i)


class TestSDFormat:
    def test_encode(self):
        assert encode_format_sd() == b"\x01"
        assert encode_format_sd(1) == b"\x01"

    def test_decode_ack_success(self):
        assert decode_format_sd_ack(b"\x01") is True

    def test_decode_ack_failure(self):
        with pytest.raises(ResponseError):
            decode_format_sd_ack(b"\x00")


class TestPicNameType:
    def test_encode_get(self):
        assert encode_get_pic_name_type(FileType.PICTURE) == b"\x00"
        assert encode_get_pic_name_type(FileType.TEMP_RAW) == b"\x01"

    def test_decode_get(self):
        payload = b"\x00\x01"
        result = decode_get_pic_name_type(payload)
        assert result == FileNameType.INDEX

    def test_encode_set(self):
        payload = encode_set_pic_name_type(FileType.PICTURE, FileNameType.TIMESTAMP)
        assert payload == b"\x00\x02"

    def test_decode_set_ack(self):
        decode_set_pic_name_type_ack(b"\x00\x02")  # Should not raise


class TestOSDFlag:
    def test_encode_get(self):
        assert encode_get_osd_flag() == b""

    def test_decode_get(self):
        assert decode_get_osd_flag(b"\x00") is False
        assert decode_get_osd_flag(b"\x01") is True

    def test_encode_set(self):
        assert encode_set_osd_flag(True) == b"\x01"
        assert encode_set_osd_flag(False) == b"\x00"

    def test_decode_set_ack(self):
        assert decode_set_osd_flag_ack(b"\x01") is True
        assert decode_set_osd_flag_ack(b"\x00") is False
