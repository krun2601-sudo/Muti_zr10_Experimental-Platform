# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Thermal imaging command encoders and decoders.

Commands: 0x12-0x14, 0x1A, 0x1B, 0x33-0x3C, 0x42-0x47, 0x4F

This module implements encoding/decoding for thermal imaging commands including:
- Temperature measurement (point, region, global)
- Pseudo color palette
- Thermal output mode
- Thermal gain
- Environmental correction
- IR threshold parameters
- Manual shutter
"""

from __future__ import annotations

import struct

from siyi_sdk.constants import (
    CMD_GET_IR_THRESH_MAP_STA,
    CMD_GET_IR_THRESH_PARAM,
    CMD_GET_IR_THRESH_PRECISION,
    CMD_GET_SINGLE_TEMP_FRAME,
    CMD_GET_TEMP_AT_POINT,
    CMD_GLOBAL_TEMP_MEASUREMENT,
    CMD_LOCAL_TEMP_MEASUREMENT,
    CMD_MANUAL_THERMAL_SHUTTER,
    CMD_REQUEST_ENV_CORRECTION_PARAMS,
    CMD_REQUEST_ENV_CORRECTION_SWITCH,
    CMD_REQUEST_PSEUDO_COLOR,
    CMD_REQUEST_THERMAL_GAIN,
    CMD_REQUEST_THERMAL_OUTPUT_MODE,
    CMD_SET_ENV_CORRECTION_PARAMS,
    CMD_SET_ENV_CORRECTION_SWITCH,
    CMD_SET_IR_THRESH_MAP_STA,
    CMD_SET_IR_THRESH_PARAM,
    CMD_SET_IR_THRESH_PRECISION,
    CMD_SET_PSEUDO_COLOR,
    CMD_SET_THERMAL_GAIN,
    CMD_SET_THERMAL_OUTPUT_MODE,
)
from siyi_sdk.exceptions import ConfigurationError, MalformedPayloadError, ResponseError
from siyi_sdk.models import (
    EnvCorrectionParams,
    IRThreshParams,
    IRThreshPrecision,
    IRThreshRegion,
    PseudoColor,
    TempGlobal,
    TempMeasureFlag,
    TempPoint,
    TempRegion,
    ThermalGain,
    ThermalOutputMode,
)


def encode_temp_at_point(x: int, y: int, flag: TempMeasureFlag) -> bytes:
    """Encode temperature at point request (0x12).

    Args:
        x: X coordinate (0-65535).
        y: Y coordinate (0-65535).
        flag: Measurement flag.

    Returns:
        5-byte payload (2xuint16 LE + uint8).

    Raises:
        ConfigurationError: If coordinates are out of range or flag is invalid.

    """
    if not 0 <= x <= 0xFFFF:
        raise ConfigurationError(f"x must be in [0,65535], got {x}")
    if not 0 <= y <= 0xFFFF:
        raise ConfigurationError(f"y must be in [0,65535], got {y}")
    if not isinstance(flag, TempMeasureFlag):
        raise ConfigurationError(f"flag must be a TempMeasureFlag, got {flag}")
    return struct.pack("<HHB", x, y, flag)


def decode_temp_at_point(payload: bytes) -> TempPoint:
    """Decode temperature at point response (0x12).

    Args:
        payload: 6 bytes (3xuint16 LE).

    Returns:
        TempPoint dataclass with temperature divided by 100.

    Raises:
        MalformedPayloadError: If payload length is not 6 bytes.

    """
    if len(payload) != 6:
        raise MalformedPayloadError(
            cmd_id=CMD_GET_TEMP_AT_POINT,
            reason=f"expected 6 bytes, got {len(payload)}",
        )
    temp_raw, x, y = struct.unpack("<HHH", payload)
    return TempPoint(x=x, y=y, temperature_c=temp_raw / 100.0)


def encode_local_temp(
    startx: int, starty: int, endx: int, endy: int, flag: TempMeasureFlag
) -> bytes:
    """Encode local temperature measurement request (0x13).

    Args:
        startx: Start X coordinate.
        starty: Start Y coordinate.
        endx: End X coordinate.
        endy: End Y coordinate.
        flag: Measurement flag.

    Returns:
        9-byte payload (4xuint16 LE + uint8).

    Raises:
        ConfigurationError: If parameters are invalid.

    """
    if not isinstance(flag, TempMeasureFlag):
        raise ConfigurationError(f"flag must be a TempMeasureFlag, got {flag}")
    return struct.pack("<HHHHB", startx, starty, endx, endy, flag)


def decode_local_temp(payload: bytes) -> TempRegion:
    """Decode local temperature measurement response (0x13).

    Args:
        payload: 20 bytes (10xuint16 LE).

    Returns:
        TempRegion dataclass with temperatures divided by 100.

    Raises:
        MalformedPayloadError: If payload length is not 20 bytes.

    """
    if len(payload) != 20:
        raise MalformedPayloadError(
            cmd_id=CMD_LOCAL_TEMP_MEASUREMENT,
            reason=f"expected 20 bytes, got {len(payload)}",
        )
    values = struct.unpack("<HHHHHHHHHH", payload)
    return TempRegion(
        startx=values[0],
        starty=values[1],
        endx=values[2],
        endy=values[3],
        max_c=values[4] / 100.0,
        min_c=values[5] / 100.0,
        max_x=values[6],
        max_y=values[7],
        min_x=values[8],
        min_y=values[9],
    )


def encode_global_temp(flag: TempMeasureFlag) -> bytes:
    """Encode global temperature measurement request (0x14).

    Args:
        flag: Measurement flag.

    Returns:
        1-byte payload (uint8).

    Raises:
        ConfigurationError: If flag is invalid.

    """
    if not isinstance(flag, TempMeasureFlag):
        raise ConfigurationError(f"flag must be a TempMeasureFlag, got {flag}")
    return struct.pack("<B", flag)


def decode_global_temp(payload: bytes) -> TempGlobal:
    """Decode global temperature measurement response (0x14).

    Args:
        payload: 12 bytes (6xuint16 LE).

    Returns:
        TempGlobal dataclass with temperatures divided by 100.

    Raises:
        MalformedPayloadError: If payload length is not 12 bytes.

    """
    if len(payload) != 12:
        raise MalformedPayloadError(
            cmd_id=CMD_GLOBAL_TEMP_MEASUREMENT,
            reason=f"expected 12 bytes, got {len(payload)}",
        )
    values = struct.unpack("<HHHHHH", payload)
    return TempGlobal(
        max_c=values[0] / 100.0,
        min_c=values[1] / 100.0,
        max_x=values[2],
        max_y=values[3],
        min_x=values[4],
        min_y=values[5],
    )


def encode_get_pseudo_color() -> bytes:
    """Encode get pseudo color request (0x1A).

    Returns:
        Empty payload.

    """
    return b""


def decode_pseudo_color(payload: bytes) -> PseudoColor:
    """Decode pseudo color response (0x1A).

    Args:
        payload: 1-byte color mode.

    Returns:
        PseudoColor enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_PSEUDO_COLOR,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (color,) = struct.unpack("<B", payload)
    return PseudoColor(color)


def encode_set_pseudo_color(c: PseudoColor) -> bytes:
    """Encode set pseudo color request (0x1B).

    Args:
        c: Pseudo color mode (0-11).

    Returns:
        1-byte payload (uint8).

    Raises:
        ConfigurationError: If c is not a valid PseudoColor.

    """
    if not isinstance(c, PseudoColor):
        raise ConfigurationError(f"c must be a PseudoColor, got {c}")
    return struct.pack("<B", c)


def decode_set_pseudo_color_ack(payload: bytes) -> PseudoColor:
    """Decode set pseudo color acknowledgment (0x1B).

    Args:
        payload: 1-byte color mode.

    Returns:
        PseudoColor enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_PSEUDO_COLOR,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (color,) = struct.unpack("<B", payload)
    return PseudoColor(color)


def encode_get_thermal_output_mode() -> bytes:
    """Encode get thermal output mode request (0x33).

    Returns:
        Empty payload.

    """
    return b""


def decode_thermal_output_mode(payload: bytes) -> ThermalOutputMode:
    """Decode thermal output mode response (0x33).

    Args:
        payload: 1-byte mode.

    Returns:
        ThermalOutputMode enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_THERMAL_OUTPUT_MODE,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (mode,) = struct.unpack("<B", payload)
    return ThermalOutputMode(mode)


def encode_set_thermal_output_mode(m: ThermalOutputMode) -> bytes:
    """Encode set thermal output mode request (0x34).

    Args:
        m: Thermal output mode (0=30fps, 1=25fps+temp).

    Returns:
        1-byte payload (uint8).

    Raises:
        ConfigurationError: If m is not a valid ThermalOutputMode.

    """
    if not isinstance(m, ThermalOutputMode):
        raise ConfigurationError(f"m must be a ThermalOutputMode, got {m}")
    return struct.pack("<B", m)


def decode_set_thermal_output_mode_ack(payload: bytes) -> ThermalOutputMode:
    """Decode set thermal output mode acknowledgment (0x34).

    Args:
        payload: 1-byte mode.

    Returns:
        ThermalOutputMode enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_THERMAL_OUTPUT_MODE,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (mode,) = struct.unpack("<B", payload)
    return ThermalOutputMode(mode)


def encode_get_single_temp_frame() -> bytes:
    """Encode get single temperature frame request (0x35).

    Returns:
        Empty payload.

    """
    return b""


def decode_single_temp_frame_ack(payload: bytes) -> bool:
    """Decode single temperature frame acknowledgment (0x35).

    Args:
        payload: 1-byte acknowledgment.

    Returns:
        True if successful.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.
        ResponseError: If acknowledgment is 0 (failure).

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_GET_SINGLE_TEMP_FRAME,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (ack,) = struct.unpack("<B", payload)
    if ack == 0:
        raise ResponseError(cmd_id=CMD_GET_SINGLE_TEMP_FRAME, sta=ack)
    return True


def encode_get_thermal_gain() -> bytes:
    """Encode get thermal gain request (0x37).

    Returns:
        Empty payload.

    """
    return b""


def decode_thermal_gain(payload: bytes) -> ThermalGain:
    """Decode thermal gain response (0x37).

    Args:
        payload: 1-byte gain mode.

    Returns:
        ThermalGain enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_THERMAL_GAIN,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (gain,) = struct.unpack("<B", payload)
    return ThermalGain(gain)


def encode_set_thermal_gain(g: ThermalGain) -> bytes:
    """Encode set thermal gain request (0x38).

    Args:
        g: Thermal gain mode (0=low, 1=high).

    Returns:
        1-byte payload (uint8).

    Raises:
        ConfigurationError: If g is not a valid ThermalGain.

    """
    if not isinstance(g, ThermalGain):
        raise ConfigurationError(f"g must be a ThermalGain, got {g}")
    return struct.pack("<B", g)


def decode_set_thermal_gain_ack(payload: bytes) -> ThermalGain:
    """Decode set thermal gain acknowledgment (0x38).

    Args:
        payload: 1-byte gain mode.

    Returns:
        ThermalGain enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_THERMAL_GAIN,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (gain,) = struct.unpack("<B", payload)
    return ThermalGain(gain)


def encode_get_env_correction_params() -> bytes:
    """Encode get environmental correction params request (0x39).

    Returns:
        Empty payload.

    """
    return b""


def decode_env_correction_params(payload: bytes) -> EnvCorrectionParams:
    """Decode environmental correction params response (0x39).

    Args:
        payload: 10 bytes (5xuint16 LE, divided by 100).

    Returns:
        EnvCorrectionParams dataclass.

    Raises:
        MalformedPayloadError: If payload length is not 10 bytes.

    """
    if len(payload) != 10:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_ENV_CORRECTION_PARAMS,
            reason=f"expected 10 bytes, got {len(payload)}",
        )
    dist, ems, hum, ta, tu = struct.unpack("<HHHHH", payload)
    return EnvCorrectionParams(
        distance_m=dist / 100.0,
        emissivity_pct=ems / 100.0,
        humidity_pct=hum / 100.0,
        ambient_c=ta / 100.0,
        reflective_c=tu / 100.0,
    )


def encode_set_env_correction_params(p: EnvCorrectionParams) -> bytes:
    """Encode set environmental correction params request (0x3A).

    Args:
        p: EnvCorrectionParams dataclass.

    Returns:
        10-byte payload (5xuint16 LE, multiplied by 100).

    """
    return struct.pack(
        "<HHHHH",
        round(p.distance_m * 100),
        round(p.emissivity_pct * 100),
        round(p.humidity_pct * 100),
        round(p.ambient_c * 100),
        round(p.reflective_c * 100),
    )


def decode_set_env_correction_params_ack(payload: bytes) -> bool:
    """Decode set environmental correction params acknowledgment (0x3A).

    Args:
        payload: 1-byte acknowledgment.

    Returns:
        True if successful.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.
        ResponseError: If acknowledgment is 0 (failure).

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_ENV_CORRECTION_PARAMS,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (ack,) = struct.unpack("<B", payload)
    if ack == 0:
        raise ResponseError(cmd_id=CMD_SET_ENV_CORRECTION_PARAMS, sta=ack)
    return True


def encode_get_env_correction_switch() -> bytes:
    """Encode get environmental correction switch request (0x3B).

    Returns:
        Empty payload.

    """
    return b""


def decode_env_correction_switch(payload: bytes) -> bool:
    """Decode environmental correction switch response (0x3B).

    Args:
        payload: 1-byte switch state.

    Returns:
        True if enabled.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_ENV_CORRECTION_SWITCH,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (switch,) = struct.unpack("<B", payload)
    return bool(switch)


def encode_set_env_correction_switch(on: bool) -> bytes:
    """Encode set environmental correction switch request (0x3C).

    Args:
        on: True to enable correction.

    Returns:
        1-byte payload (uint8).

    """
    return struct.pack("<B", int(on))


def decode_set_env_correction_switch_ack(payload: bytes) -> bool:
    """Decode set environmental correction switch acknowledgment (0x3C).

    Args:
        payload: 1-byte switch state.

    Returns:
        True if now enabled.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_ENV_CORRECTION_SWITCH,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (switch,) = struct.unpack("<B", payload)
    return bool(switch)


def encode_get_ir_thresh_map_state() -> bytes:
    """Encode get IR threshold map state request (0x42).

    Returns:
        Empty payload.

    """
    return b""


def decode_ir_thresh_map_state(payload: bytes) -> bool:
    """Decode IR threshold map state response (0x42).

    Args:
        payload: 1-byte state.

    Returns:
        True if enabled.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_GET_IR_THRESH_MAP_STA,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (state,) = struct.unpack("<B", payload)
    return bool(state)


def encode_set_ir_thresh_map_state(on: bool) -> bytes:
    """Encode set IR threshold map state request (0x43).

    Args:
        on: True to enable threshold map.

    Returns:
        1-byte payload (uint8).

    """
    return struct.pack("<B", int(on))


def decode_set_ir_thresh_map_state_ack(payload: bytes) -> bool:
    """Decode set IR threshold map state acknowledgment (0x43).

    Args:
        payload: 1-byte state.

    Returns:
        True if now enabled.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_IR_THRESH_MAP_STA,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (state,) = struct.unpack("<B", payload)
    return bool(state)


def encode_get_ir_thresh_params() -> bytes:
    """Encode get IR threshold params request (0x44).

    Returns:
        Empty payload.

    """
    return b""


def decode_ir_thresh_params(payload: bytes) -> IRThreshParams:
    """Decode IR threshold params response (0x44).

    Args:
        payload: 24 bytes (3 x [uint8 + 2xint16 LE + 3xuint8]).

    Returns:
        IRThreshParams dataclass.

    Raises:
        MalformedPayloadError: If payload length is not 24 bytes.

    """
    if len(payload) != 24:
        raise MalformedPayloadError(
            cmd_id=CMD_GET_IR_THRESH_PARAM,
            reason=f"expected 24 bytes, got {len(payload)}",
        )
    # Each region: switch(1) + temp_min(2) + temp_max(2) + r(1) + g(1) + b(1) = 8 bytes
    # 3 regions x 8 bytes = 24 bytes total

    if len(payload) != 24:
        raise MalformedPayloadError(
            cmd_id=CMD_GET_IR_THRESH_PARAM,
            reason=f"expected 24 bytes, got {len(payload)}",
        )

    def parse_region(data: bytes) -> IRThreshRegion:
        switch, temp_min, temp_max, r, g, b = struct.unpack("<BhhBBB", data)
        return IRThreshRegion(
            switch=switch,
            temp_min=temp_min,
            temp_max=temp_max,
            color_r=r,
            color_g=g,
            color_b=b,
        )

    region1 = parse_region(payload[0:8])
    region2 = parse_region(payload[8:16])
    region3 = parse_region(payload[16:24])
    return IRThreshParams(region1=region1, region2=region2, region3=region3)


def encode_set_ir_thresh_params(p: IRThreshParams) -> bytes:
    """Encode set IR threshold params request (0x45).

    Args:
        p: IRThreshParams dataclass.

    Returns:
        24-byte payload (3 x [uint8 + 2xint16 LE + 3xint8]).

    """

    def encode_region(r: IRThreshRegion) -> bytes:
        return struct.pack(
            "<BhhBBB",
            r.switch,
            r.temp_min,
            r.temp_max,
            r.color_r,
            r.color_g,
            r.color_b,
        )

    return encode_region(p.region1) + encode_region(p.region2) + encode_region(p.region3)


def decode_set_ir_thresh_params_ack(payload: bytes) -> bool:
    """Decode set IR threshold params acknowledgment (0x45).

    Args:
        payload: 1-byte acknowledgment.

    Returns:
        True if successful.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.
        ResponseError: If acknowledgment is 0 (failure).

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_IR_THRESH_PARAM,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (ack,) = struct.unpack("<B", payload)
    if ack == 0:
        raise ResponseError(cmd_id=CMD_SET_IR_THRESH_PARAM, sta=ack)
    return True


def encode_get_ir_thresh_precision() -> bytes:
    """Encode get IR threshold precision request (0x46).

    Returns:
        Empty payload.

    """
    return b""


def decode_ir_thresh_precision(payload: bytes) -> IRThreshPrecision:
    """Decode IR threshold precision response (0x46).

    Args:
        payload: 1-byte precision (1-3).

    Returns:
        IRThreshPrecision enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_GET_IR_THRESH_PRECISION,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (precision,) = struct.unpack("<B", payload)
    return IRThreshPrecision(precision)


def encode_set_ir_thresh_precision(p: IRThreshPrecision) -> bytes:
    """Encode set IR threshold precision request (0x47).

    Args:
        p: IR threshold precision (1=max, 2=mid, 3=min).

    Returns:
        1-byte payload (uint8).

    Raises:
        ConfigurationError: If p is not a valid IRThreshPrecision.

    """
    if not isinstance(p, IRThreshPrecision):
        raise ConfigurationError(f"p must be an IRThreshPrecision, got {p}")
    return struct.pack("<B", p)


def decode_set_ir_thresh_precision_ack(payload: bytes) -> IRThreshPrecision:
    """Decode set IR threshold precision acknowledgment (0x47).

    Args:
        payload: 1-byte precision.

    Returns:
        IRThreshPrecision enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_IR_THRESH_PRECISION,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (precision,) = struct.unpack("<B", payload)
    return IRThreshPrecision(precision)


def encode_manual_thermal_shutter() -> bytes:
    """Encode manual thermal shutter request (0x4F).

    Returns:
        Empty payload.

    """
    return b""


def decode_manual_thermal_shutter_ack(payload: bytes) -> bool:
    """Decode manual thermal shutter acknowledgment (0x4F).

    Args:
        payload: 1-byte acknowledgment.

    Returns:
        True if successful.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.
        ResponseError: If acknowledgment is 0 (failure).

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_MANUAL_THERMAL_SHUTTER,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (ack,) = struct.unpack("<B", payload)
    if ack == 0:
        raise ResponseError(cmd_id=CMD_MANUAL_THERMAL_SHUTTER, sta=ack)
    return True
