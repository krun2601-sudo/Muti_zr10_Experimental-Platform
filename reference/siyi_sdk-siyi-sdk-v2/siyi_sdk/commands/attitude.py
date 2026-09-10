# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Attitude and motion command encoders and decoders (0x0D, 0x22, 0x24, 0x25, 0x26, 0x3E).

This module implements encoding/decoding for attitude and motion commands including:
- Gimbal attitude query
- Aircraft attitude send
- Data stream control
- Magnetic encoder query
- Raw GPS send
"""

from __future__ import annotations

import struct

from siyi_sdk.constants import (
    CMD_REQUEST_FC_DATA_STREAM,
    CMD_REQUEST_GIMBAL_ATTITUDE,
    CMD_REQUEST_GIMBAL_DATA_STREAM,
    CMD_REQUEST_MAGNETIC_ENCODER,
)
from siyi_sdk.exceptions import ConfigurationError, MalformedPayloadError
from siyi_sdk.models import (
    AircraftAttitude,
    DataStreamFreq,
    FCDataType,
    GimbalAttitude,
    GimbalDataType,
    MagneticEncoderAngles,
    RawGPS,
)


def encode_gimbal_attitude() -> bytes:
    """Encode gimbal attitude request (0x0D).

    Returns:
        Empty payload.

    """
    return b""


def decode_gimbal_attitude(payload: bytes) -> GimbalAttitude:
    """Decode gimbal attitude response (0x0D).

    Args:
        payload: 12 bytes (6 x int16 LE, divided by 10).

    Returns:
        GimbalAttitude dataclass with angles in degrees and rates in deg/s.

    Raises:
        MalformedPayloadError: If payload length is not 12 bytes.

    """
    if len(payload) != 12:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_GIMBAL_ATTITUDE,
            reason=f"expected 12 bytes, got {len(payload)}",
        )
    yaw, pitch, roll, yaw_vel, pitch_vel, roll_vel = struct.unpack("<hhhhhh", payload)
    return GimbalAttitude(
        yaw_deg=yaw / 10.0,
        pitch_deg=pitch / 10.0,
        roll_deg=roll / 10.0,
        yaw_rate_dps=yaw_vel / 10.0,
        pitch_rate_dps=pitch_vel / 10.0,
        roll_rate_dps=roll_vel / 10.0,
    )


def encode_aircraft_attitude(att: AircraftAttitude) -> bytes:
    """Encode aircraft attitude send (0x22).

    Args:
        att: AircraftAttitude dataclass with angles in radians.

    Returns:
        28-byte payload (uint32 + 6 x float LE).

    """
    return struct.pack(
        "<Iffffff",
        att.time_boot_ms,
        att.roll_rad,
        att.pitch_rad,
        att.yaw_rad,
        att.rollspeed,
        att.pitchspeed,
        att.yawspeed,
    )


def encode_fc_stream(data_type: FCDataType, freq: DataStreamFreq) -> bytes:
    """Encode FC data stream request (0x24).

    Args:
        data_type: Data type (1=attitude, 2=rc_channels).
        freq: Stream frequency.

    Returns:
        2-byte payload (2 x uint8).

    Raises:
        ConfigurationError: If data_type is not valid.

    """
    if data_type not in (FCDataType.ATTITUDE, FCDataType.RC_CHANNELS):
        raise ConfigurationError(f"data_type must be 1 or 2, got {data_type}")
    return struct.pack("<BB", data_type, freq)


def decode_fc_stream_ack(payload: bytes) -> FCDataType:
    """Decode FC data stream acknowledgment (0x24).

    Args:
        payload: 1-byte data type.

    Returns:
        FCDataType enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_FC_DATA_STREAM,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (data_type,) = struct.unpack("<B", payload)
    return FCDataType(data_type)


def encode_gimbal_stream(data_type: GimbalDataType, freq: DataStreamFreq) -> bytes:
    """Encode gimbal data stream request (0x25).

    Args:
        data_type: Data type (1=attitude, 2=laser, 3=encoder, 4=motor_voltage).
        freq: Stream frequency (ignored for laser).

    Returns:
        2-byte payload (2 x uint8).

    Raises:
        ConfigurationError: If data_type is not valid.

    """
    if data_type not in (
        GimbalDataType.ATTITUDE,
        GimbalDataType.LASER_RANGE,
        GimbalDataType.MAGNETIC_ENCODER,
        GimbalDataType.MOTOR_VOLTAGE,
    ):
        raise ConfigurationError(f"data_type must be 1-4, got {data_type}")
    return struct.pack("<BB", data_type, freq)


def decode_gimbal_stream_ack(payload: bytes) -> GimbalDataType:
    """Decode gimbal data stream acknowledgment (0x25).

    Args:
        payload: 1-byte data type.

    Returns:
        GimbalDataType enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_GIMBAL_DATA_STREAM,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (data_type,) = struct.unpack("<B", payload)
    return GimbalDataType(data_type)


def encode_magnetic_encoder() -> bytes:
    """Encode magnetic encoder request (0x26).

    Returns:
        Empty payload.

    """
    return b""


def decode_magnetic_encoder(payload: bytes) -> MagneticEncoderAngles:
    """Decode magnetic encoder response (0x26).

    Args:
        payload: 6 bytes (3 x int16 LE, divided by 10).

    Returns:
        MagneticEncoderAngles dataclass with angles in degrees.

    Raises:
        MalformedPayloadError: If payload length is not 6 bytes.

    """
    if len(payload) != 6:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_MAGNETIC_ENCODER,
            reason=f"expected 6 bytes, got {len(payload)}",
        )
    yaw, pitch, roll = struct.unpack("<hhh", payload)
    return MagneticEncoderAngles(
        yaw=yaw / 10.0,
        pitch=pitch / 10.0,
        roll=roll / 10.0,
    )


def encode_raw_gps(gps: RawGPS) -> bytes:
    """Encode raw GPS send (0x3E).

    Args:
        gps: RawGPS dataclass.

    Returns:
        32-byte payload (uint32 + 7 x int32 LE).

    """
    return struct.pack(
        "<Iiiiiiii",
        gps.time_boot_ms,
        gps.lat_e7,
        gps.lon_e7,
        gps.alt_msl_cm,
        gps.alt_ellipsoid_cm,
        gps.vn_mmps,
        gps.ve_mmps,
        gps.vd_mmps,
    )
