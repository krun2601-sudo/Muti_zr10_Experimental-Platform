# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Extended tests for thermal commands."""

import struct

import pytest

from siyi_sdk.commands.thermal import (
    decode_env_correction_params,
    decode_env_correction_switch,
    decode_global_temp,
    decode_ir_thresh_map_state,
    decode_ir_thresh_params,
    decode_ir_thresh_precision,
    decode_local_temp,
    decode_manual_thermal_shutter_ack,
    decode_set_env_correction_params_ack,
    decode_set_env_correction_switch_ack,
    decode_set_ir_thresh_map_state_ack,
    decode_set_ir_thresh_params_ack,
    decode_set_ir_thresh_precision_ack,
    decode_set_thermal_output_mode_ack,
    decode_single_temp_frame_ack,
    decode_thermal_output_mode,
    encode_get_env_correction_params,
    encode_get_env_correction_switch,
    encode_get_ir_thresh_map_state,
    encode_get_ir_thresh_params,
    encode_get_ir_thresh_precision,
    encode_get_single_temp_frame,
    encode_get_thermal_output_mode,
    encode_global_temp,
    encode_local_temp,
    encode_manual_thermal_shutter,
    encode_set_env_correction_params,
    encode_set_env_correction_switch,
    encode_set_ir_thresh_map_state,
    encode_set_ir_thresh_params,
    encode_set_ir_thresh_precision,
    encode_set_thermal_output_mode,
)
from siyi_sdk.exceptions import ResponseError
from siyi_sdk.models import (
    EnvCorrectionParams,
    IRThreshParams,
    IRThreshPrecision,
    IRThreshRegion,
    TempMeasureFlag,
    ThermalOutputMode,
)


class TestLocalTemp:
    def test_encode(self):
        payload = encode_local_temp(0, 0, 100, 100, TempMeasureFlag.MEASURE_ONCE)
        assert len(payload) == 9

    def test_decode(self):
        # 10 x uint16: startx, starty, endx, endy, max_c, min_c, max_x, max_y, min_x, min_y
        payload = struct.pack("<HHHHHHHHHH", 0, 0, 100, 100, 3500, 2000, 50, 50, 10, 10)
        result = decode_local_temp(payload)
        assert result.startx == 0
        assert result.max_c == 35.0
        assert result.min_c == 20.0


class TestGlobalTemp:
    def test_encode(self):
        payload = encode_global_temp(TempMeasureFlag.CONTINUOUS_5HZ)
        assert payload == b"\x02"

    def test_decode(self):
        # 6 x uint16: max_c, min_c, max_x, max_y, min_x, min_y
        payload = struct.pack("<HHHHHH", 4000, 1500, 320, 240, 100, 50)
        result = decode_global_temp(payload)
        assert result.max_c == 40.0
        assert result.min_c == 15.0
        assert result.max_x == 320
        assert result.min_y == 50


class TestThermalOutputMode:
    def test_encode_get(self):
        assert encode_get_thermal_output_mode() == b""

    def test_decode(self):
        assert decode_thermal_output_mode(b"\x00") == ThermalOutputMode.FPS30
        assert decode_thermal_output_mode(b"\x01") == ThermalOutputMode.FPS25_PLUS_TEMP

    def test_encode_set(self):
        assert encode_set_thermal_output_mode(ThermalOutputMode.FPS30) == b"\x00"

    def test_decode_ack(self):
        assert decode_set_thermal_output_mode_ack(b"\x01") == ThermalOutputMode.FPS25_PLUS_TEMP


class TestSingleTempFrame:
    def test_encode(self):
        assert encode_get_single_temp_frame() == b""

    def test_decode_ack_success(self):
        assert decode_single_temp_frame_ack(b"\x01") is True

    def test_decode_ack_failure(self):
        with pytest.raises(ResponseError):
            decode_single_temp_frame_ack(b"\x00")


class TestEnvCorrection:
    def test_encode_get_params(self):
        assert encode_get_env_correction_params() == b""

    def test_decode_params(self):
        # 5 x uint16 / 100
        payload = struct.pack("<HHHHH", 10000, 9500, 5000, 2500, 2000)
        result = decode_env_correction_params(payload)
        assert result.distance_m == 100.0
        assert result.emissivity_pct == 95.0
        assert result.humidity_pct == 50.0
        assert result.ambient_c == 25.0
        assert result.reflective_c == 20.0

    def test_encode_set_params(self):
        p = EnvCorrectionParams(
            distance_m=50.0,
            emissivity_pct=90.0,
            humidity_pct=60.0,
            ambient_c=22.0,
            reflective_c=18.0,
        )
        payload = encode_set_env_correction_params(p)
        assert len(payload) == 10

    def test_decode_set_params_ack_success(self):
        assert decode_set_env_correction_params_ack(b"\x01") is True

    def test_decode_set_params_ack_failure(self):
        with pytest.raises(ResponseError):
            decode_set_env_correction_params_ack(b"\x00")

    def test_encode_get_switch(self):
        assert encode_get_env_correction_switch() == b""

    def test_decode_switch(self):
        assert decode_env_correction_switch(b"\x00") is False
        assert decode_env_correction_switch(b"\x01") is True

    def test_encode_set_switch(self):
        assert encode_set_env_correction_switch(True) == b"\x01"

    def test_decode_set_switch_ack(self):
        assert decode_set_env_correction_switch_ack(b"\x01") is True


class TestIRThreshMap:
    def test_encode_get_state(self):
        assert encode_get_ir_thresh_map_state() == b""

    def test_decode_state(self):
        assert decode_ir_thresh_map_state(b"\x00") is False
        assert decode_ir_thresh_map_state(b"\x01") is True

    def test_encode_set_state(self):
        assert encode_set_ir_thresh_map_state(True) == b"\x01"

    def test_decode_set_state_ack(self):
        assert decode_set_ir_thresh_map_state_ack(b"\x01") is True


class TestIRThreshParams:
    def test_encode_get(self):
        assert encode_get_ir_thresh_params() == b""

    def test_decode(self):
        # 3 regions x 8 bytes: switch, temp_min, temp_max, r, g, b
        region_data = struct.pack("<BhhBBB", 1, 100, 200, 255, 0, 0)
        payload = region_data * 3
        result = decode_ir_thresh_params(payload)
        assert result.region1.switch == 1
        assert result.region1.temp_min == 100
        assert result.region1.color_r == 255

    def test_encode_set(self):
        r1 = IRThreshRegion(1, 100, 200, 255, 0, 0)
        r2 = IRThreshRegion(1, 300, 400, 0, 255, 0)
        r3 = IRThreshRegion(0, 0, 0, 0, 0, 0)
        p = IRThreshParams(r1, r2, r3)
        payload = encode_set_ir_thresh_params(p)
        assert len(payload) == 24

    def test_decode_set_ack_success(self):
        assert decode_set_ir_thresh_params_ack(b"\x01") is True

    def test_decode_set_ack_failure(self):
        with pytest.raises(ResponseError):
            decode_set_ir_thresh_params_ack(b"\x00")


class TestIRThreshPrecision:
    def test_encode_get(self):
        assert encode_get_ir_thresh_precision() == b""

    def test_decode(self):
        assert decode_ir_thresh_precision(b"\x01") == IRThreshPrecision.MAX
        assert decode_ir_thresh_precision(b"\x02") == IRThreshPrecision.MID
        assert decode_ir_thresh_precision(b"\x03") == IRThreshPrecision.MIN

    def test_encode_set(self):
        assert encode_set_ir_thresh_precision(IRThreshPrecision.MAX) == b"\x01"

    def test_decode_ack(self):
        assert decode_set_ir_thresh_precision_ack(b"\x02") == IRThreshPrecision.MID


class TestManualThermalShutter:
    def test_encode(self):
        assert encode_manual_thermal_shutter() == b""

    def test_decode_ack_success(self):
        assert decode_manual_thermal_shutter_ack(b"\x01") is True

    def test_decode_ack_failure(self):
        with pytest.raises(ResponseError):
            decode_manual_thermal_shutter_ack(b"\x00")
