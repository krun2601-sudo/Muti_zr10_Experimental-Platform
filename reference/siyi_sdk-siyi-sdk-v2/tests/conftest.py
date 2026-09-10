# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Top-level pytest fixtures for comprehensive test coverage.

This module provides fixtures for:
- Event loop configuration
- Mock transport and connected client instances
- Sample Frame fixtures for every CMD_ID in the protocol
- Reusable test data for integration and unit tests
"""

from __future__ import annotations

import asyncio
import struct
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from siyi_sdk.client import SIYIClient
from siyi_sdk.constants import (
    CMD_ABSOLUTE_ZOOM_AUTO_FOCUS,
    CMD_AI_TRACK_STREAM,
    CMD_AUTO_FOCUS,
    CMD_FUNCTION_FEEDBACK,
    CMD_GET_AI_TRACK_STREAM_STA,
    CMD_GET_IP,
    CMD_GET_MAVLINK_OSD_FLAG,
    CMD_GET_PIC_NAME_TYPE,
    CMD_GIMBAL_ROTATION,
    CMD_MANUAL_FOCUS,
    CMD_MANUAL_ZOOM_AUTO_FOCUS,
    CMD_ONE_KEY_CENTERING,
    CMD_REQUEST_CAMERA_SYSTEM_INFO,
    CMD_REQUEST_CONTROL_MODE,
    CMD_REQUEST_ENCODING_PARAMS,
    CMD_REQUEST_ENV_CORRECTION_PARAMS,
    CMD_REQUEST_ENV_CORRECTION_SWITCH,
    CMD_REQUEST_FIRMWARE_VERSION,
    CMD_REQUEST_GIMBAL_ATTITUDE,
    CMD_REQUEST_GIMBAL_DATA_STREAM,
    CMD_REQUEST_GIMBAL_MODE,
    CMD_REQUEST_GIMBAL_SYSTEM_INFO,
    CMD_REQUEST_HARDWARE_ID,
    CMD_REQUEST_LASER_DISTANCE,
    CMD_REQUEST_LASER_LATLON,
    CMD_REQUEST_MAGNETIC_ENCODER,
    CMD_REQUEST_MOTOR_VOLTAGE,
    CMD_REQUEST_PSEUDO_COLOR,
    CMD_REQUEST_SYSTEM_TIME,
    CMD_REQUEST_THERMAL_GAIN,
    CMD_REQUEST_THERMAL_OUTPUT_MODE,
    CMD_REQUEST_VIDEO_STITCHING_MODE,
    CMD_REQUEST_WEAK_CONTROL_MODE,
    CMD_REQUEST_WEAK_THRESHOLD,
    CMD_REQUEST_ZOOM_MAGNIFICATION,
    CMD_REQUEST_ZOOM_RANGE,
    CMD_SD_FORMAT,
    CMD_SET_AI_TRACK_STREAM_STA,
    CMD_SET_ENCODING_PARAMS,
    CMD_SET_ENV_CORRECTION_PARAMS,
    CMD_SET_ENV_CORRECTION_SWITCH,
    CMD_SET_GIMBAL_ATTITUDE,
    CMD_SET_IP,
    CMD_SET_LASER_RANGING_STATE,
    CMD_SET_MAVLINK_OSD_FLAG,
    CMD_SET_PIC_NAME_TYPE,
    CMD_SET_PSEUDO_COLOR,
    CMD_SET_THERMAL_GAIN,
    CMD_SET_THERMAL_OUTPUT_MODE,
    CMD_SET_UTC_TIME,
    CMD_SET_VIDEO_STITCHING_MODE,
    CMD_SET_WEAK_CONTROL_MODE,
    CMD_SET_WEAK_THRESHOLD,
    CMD_SINGLE_AXIS_ATTITUDE,
    CMD_SOFT_REBOOT,
    CMD_TCP_HEARTBEAT,
    CTRL_ACK_PACK,
    CTRL_NEED_ACK,
)
from siyi_sdk.protocol.frame import Frame
from siyi_sdk.transport.mock import MockTransport


@pytest.fixture(scope="session")
def event_loop() -> AsyncIterator[asyncio.AbstractEventLoop]:
    """Provide a module-scoped event loop for async tests.

    Yields:
        Event loop instance.

    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_transport() -> MockTransport:
    """Create a fresh MockTransport instance.

    Returns:
        MockTransport instance ready for use.

    """
    return MockTransport()


@pytest_asyncio.fixture
async def connected_client(mock_transport: MockTransport) -> AsyncIterator[SIYIClient]:
    """Create a connected SIYIClient with mock transport.

    Args:
        mock_transport: MockTransport fixture.

    Yields:
        Connected SIYIClient instance.

    """
    client = SIYIClient(mock_transport, default_timeout=0.5)
    await client.connect()
    yield client
    await client.close()


# =============================================================================
# Frame Fixtures — Every CMD_ID in Protocol Specification
# =============================================================================


@pytest.fixture
def frame_heartbeat_ack() -> bytes:
    """Heartbeat ACK frame (0x00)."""
    return Frame(ctrl=CTRL_ACK_PACK, seq=0, cmd_id=CMD_TCP_HEARTBEAT, data=b"").to_bytes()


@pytest.fixture
def frame_firmware_version_ack() -> bytes:
    """Firmware version ACK frame (0x01) with realistic values."""
    # Camera=0x01020304, Gimbal=0x05060708, Zoom=0x090A0B0C
    payload = struct.pack("<III", 0x01020304, 0x05060708, 0x090A0B0C)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=1, cmd_id=CMD_REQUEST_FIRMWARE_VERSION, data=payload
    ).to_bytes()


@pytest.fixture
def frame_hardware_id_ack() -> bytes:
    """Hardware ID ACK frame (0x02) — ZR10 example."""
    payload = b"6b\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0A"
    return Frame(ctrl=CTRL_ACK_PACK, seq=2, cmd_id=CMD_REQUEST_HARDWARE_ID, data=payload).to_bytes()


@pytest.fixture
def frame_auto_focus_ack() -> bytes:
    """Auto focus ACK frame (0x04) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(ctrl=CTRL_ACK_PACK, seq=3, cmd_id=CMD_AUTO_FOCUS, data=payload).to_bytes()


@pytest.fixture
def frame_manual_zoom_auto_focus_ack() -> bytes:
    """Manual zoom + auto focus ACK frame (0x05) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=4, cmd_id=CMD_MANUAL_ZOOM_AUTO_FOCUS, data=payload
    ).to_bytes()


@pytest.fixture
def frame_manual_focus_ack() -> bytes:
    """Manual focus ACK frame (0x06) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(ctrl=CTRL_ACK_PACK, seq=5, cmd_id=CMD_MANUAL_FOCUS, data=payload).to_bytes()


@pytest.fixture
def frame_gimbal_rotation_ack() -> bytes:
    """Gimbal rotation ACK frame (0x07) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(ctrl=CTRL_ACK_PACK, seq=6, cmd_id=CMD_GIMBAL_ROTATION, data=payload).to_bytes()


@pytest.fixture
def frame_one_key_centering_ack() -> bytes:
    """One-key centering ACK frame (0x08) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(ctrl=CTRL_ACK_PACK, seq=7, cmd_id=CMD_ONE_KEY_CENTERING, data=payload).to_bytes()


@pytest.fixture
def frame_camera_system_info_ack() -> bytes:
    """Camera system info ACK frame (0x0A)."""
    # recording_sta, hdmi_cvbs, gimbal_motion_mode, mounting_direction, reserved
    payload = struct.pack("<BBBBB", 1, 0, 1, 1, 0)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=8, cmd_id=CMD_REQUEST_CAMERA_SYSTEM_INFO, data=payload
    ).to_bytes()


@pytest.fixture
def frame_function_feedback_push() -> bytes:
    """Function feedback push frame (0x0B) — photo OK."""
    payload = struct.pack("<B", 0)  # PHOTO_OK
    return Frame(ctrl=CTRL_NEED_ACK, seq=9, cmd_id=CMD_FUNCTION_FEEDBACK, data=payload).to_bytes()


@pytest.fixture
def frame_gimbal_attitude_ack() -> bytes:
    """Gimbal attitude ACK frame (0x0D) with yaw=10, pitch=20, roll=30, velocities=0."""
    # yaw, pitch, roll, yaw_vel, pitch_vel, roll_vel (all * 10)
    payload = struct.pack("<hhhhhh", 100, 200, 300, 0, 0, 0)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=10, cmd_id=CMD_REQUEST_GIMBAL_ATTITUDE, data=payload
    ).to_bytes()


@pytest.fixture
def frame_set_gimbal_attitude_ack() -> bytes:
    """Set gimbal attitude ACK frame (0x0E) with sta=1, yaw=10, pitch=20."""
    payload = struct.pack("<Bhh", 1, 100, 200)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=11, cmd_id=CMD_SET_GIMBAL_ATTITUDE, data=payload
    ).to_bytes()


@pytest.fixture
def frame_absolute_zoom_ack() -> bytes:
    """Absolute zoom ACK frame (0x0F) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=12, cmd_id=CMD_ABSOLUTE_ZOOM_AUTO_FOCUS, data=payload
    ).to_bytes()


@pytest.fixture
def frame_video_stitching_mode_ack() -> bytes:
    """Video stitching mode ACK frame (0x10) — mode=3."""
    payload = struct.pack("<B", 3)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=13, cmd_id=CMD_REQUEST_VIDEO_STITCHING_MODE, data=payload
    ).to_bytes()


@pytest.fixture
def frame_set_video_stitching_mode_ack() -> bytes:
    """Set video stitching mode ACK frame (0x11) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=14, cmd_id=CMD_SET_VIDEO_STITCHING_MODE, data=payload
    ).to_bytes()


@pytest.fixture
def frame_laser_distance_ack() -> bytes:
    """Laser distance ACK frame (0x15) — 123.4 meters."""
    payload = struct.pack("<H", 1234)  # decimeters
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=15, cmd_id=CMD_REQUEST_LASER_DISTANCE, data=payload
    ).to_bytes()


@pytest.fixture
def frame_zoom_range_ack() -> bytes:
    """Zoom range ACK frame (0x16) — max_zoom_factor=30."""
    payload = struct.pack("<H", 300)  # 30.0x in tenths
    return Frame(ctrl=CTRL_ACK_PACK, seq=16, cmd_id=CMD_REQUEST_ZOOM_RANGE, data=payload).to_bytes()


@pytest.fixture
def frame_laser_latlon_ack() -> bytes:
    """Laser target lat/lon ACK frame (0x17)."""
    payload = struct.pack(
        "<iiii", 400000000, -1200000000, 500, 1000
    )  # lat, lon, alt, rel_alt in mm
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=17, cmd_id=CMD_REQUEST_LASER_LATLON, data=payload
    ).to_bytes()


@pytest.fixture
def frame_zoom_magnification_ack() -> bytes:
    """Zoom magnification ACK frame (0x18) — 5.5x, integral_part=5."""
    payload = struct.pack("<HB", 55, 5)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=18, cmd_id=CMD_REQUEST_ZOOM_MAGNIFICATION, data=payload
    ).to_bytes()


@pytest.fixture
def frame_gimbal_mode_ack() -> bytes:
    """Gimbal mode ACK frame (0x19) — FOLLOW mode."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=19, cmd_id=CMD_REQUEST_GIMBAL_MODE, data=payload
    ).to_bytes()


@pytest.fixture
def frame_pseudo_color_ack() -> bytes:
    """Pseudo color ACK frame (0x1A) — RAINBOW."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=20, cmd_id=CMD_REQUEST_PSEUDO_COLOR, data=payload
    ).to_bytes()


@pytest.fixture
def frame_set_pseudo_color_ack() -> bytes:
    """Set pseudo color ACK frame (0x1B) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(ctrl=CTRL_ACK_PACK, seq=21, cmd_id=CMD_SET_PSEUDO_COLOR, data=payload).to_bytes()


@pytest.fixture
def frame_encoding_params_ack() -> bytes:
    """Encoding params ACK frame (0x20)."""
    payload = struct.pack("<BBHBB", 2, 1, 8000, 1, 1)  # enc_type, stream, bitrate, fps_mul, fps_div
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=22, cmd_id=CMD_REQUEST_ENCODING_PARAMS, data=payload
    ).to_bytes()


@pytest.fixture
def frame_set_encoding_params_ack() -> bytes:
    """Set encoding params ACK frame (0x21) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=23, cmd_id=CMD_SET_ENCODING_PARAMS, data=payload
    ).to_bytes()


@pytest.fixture
def frame_gimbal_data_stream_ack() -> bytes:
    """Gimbal data stream ACK frame (0x25) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=24, cmd_id=CMD_REQUEST_GIMBAL_DATA_STREAM, data=payload
    ).to_bytes()


@pytest.fixture
def frame_magnetic_encoder_ack() -> bytes:
    """Magnetic encoder ACK frame (0x26) — yaw=10.0, pitch=20.0, roll=30.0."""
    payload = struct.pack("<hhh", 100, 200, 300)  # degrees * 10
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=25, cmd_id=CMD_REQUEST_MAGNETIC_ENCODER, data=payload
    ).to_bytes()


@pytest.fixture
def frame_control_mode_ack() -> bytes:
    """Control mode ACK frame (0x27) — ATTITUDE mode."""
    payload = struct.pack("<B", 0)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=26, cmd_id=CMD_REQUEST_CONTROL_MODE, data=payload
    ).to_bytes()


@pytest.fixture
def frame_weak_threshold_ack() -> bytes:
    """Weak threshold ACK frame (0x28) — yaw=50, pitch=60."""
    payload = struct.pack("<BB", 50, 60)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=27, cmd_id=CMD_REQUEST_WEAK_THRESHOLD, data=payload
    ).to_bytes()


@pytest.fixture
def frame_set_weak_threshold_ack() -> bytes:
    """Set weak threshold ACK frame (0x29) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(ctrl=CTRL_ACK_PACK, seq=28, cmd_id=CMD_SET_WEAK_THRESHOLD, data=payload).to_bytes()


@pytest.fixture
def frame_motor_voltage_ack() -> bytes:
    """Motor voltage ACK frame (0x2A) — yaw=12.3V, pitch=11.9V, roll=12.1V."""
    payload = struct.pack("<HHH", 1230, 1190, 1210)  # in 0.01V
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=29, cmd_id=CMD_REQUEST_MOTOR_VOLTAGE, data=payload
    ).to_bytes()


@pytest.fixture
def frame_set_utc_time_ack() -> bytes:
    """Set UTC time ACK frame (0x30) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(ctrl=CTRL_ACK_PACK, seq=30, cmd_id=CMD_SET_UTC_TIME, data=payload).to_bytes()


@pytest.fixture
def frame_gimbal_system_info_ack() -> bytes:
    """Gimbal system info ACK frame (0x31)."""
    # firmware_major, firmware_minor, firmware_patch, pan_bias, tilt_bias
    payload = struct.pack("<HHHhh", 1, 2, 3, -10, 20)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=31, cmd_id=CMD_REQUEST_GIMBAL_SYSTEM_INFO, data=payload
    ).to_bytes()


@pytest.fixture
def frame_set_laser_ranging_state_ack() -> bytes:
    """Set laser ranging state ACK frame (0x32) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=32, cmd_id=CMD_SET_LASER_RANGING_STATE, data=payload
    ).to_bytes()


@pytest.fixture
def frame_thermal_output_mode_ack() -> bytes:
    """Thermal output mode ACK frame (0x33) — PIP mode."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=33, cmd_id=CMD_REQUEST_THERMAL_OUTPUT_MODE, data=payload
    ).to_bytes()


@pytest.fixture
def frame_set_thermal_output_mode_ack() -> bytes:
    """Set thermal output mode ACK frame (0x34) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=34, cmd_id=CMD_SET_THERMAL_OUTPUT_MODE, data=payload
    ).to_bytes()


@pytest.fixture
def frame_thermal_gain_ack() -> bytes:
    """Thermal gain ACK frame (0x37) — HIGH gain."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=35, cmd_id=CMD_REQUEST_THERMAL_GAIN, data=payload
    ).to_bytes()


@pytest.fixture
def frame_set_thermal_gain_ack() -> bytes:
    """Set thermal gain ACK frame (0x38) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(ctrl=CTRL_ACK_PACK, seq=36, cmd_id=CMD_SET_THERMAL_GAIN, data=payload).to_bytes()


@pytest.fixture
def frame_env_correction_params_ack() -> bytes:
    """Environment correction params ACK frame (0x39)."""
    # distance=100m, emissivity=95%, atmospheric_temp=25.0C, scene_temp=30.0C, humidity=60%
    payload = struct.pack("<HBhhB", 100, 95, 250, 300, 60)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=37, cmd_id=CMD_REQUEST_ENV_CORRECTION_PARAMS, data=payload
    ).to_bytes()


@pytest.fixture
def frame_set_env_correction_params_ack() -> bytes:
    """Set environment correction params ACK frame (0x3A) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=38, cmd_id=CMD_SET_ENV_CORRECTION_PARAMS, data=payload
    ).to_bytes()


@pytest.fixture
def frame_env_correction_switch_ack() -> bytes:
    """Environment correction switch ACK frame (0x3B) — enabled."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=39, cmd_id=CMD_REQUEST_ENV_CORRECTION_SWITCH, data=payload
    ).to_bytes()


@pytest.fixture
def frame_set_env_correction_switch_ack() -> bytes:
    """Set environment correction switch ACK frame (0x3C) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=40, cmd_id=CMD_SET_ENV_CORRECTION_SWITCH, data=payload
    ).to_bytes()


@pytest.fixture
def frame_system_time_ack() -> bytes:
    """System time ACK frame (0x40) — 2024-01-15 10:30:45."""
    payload = struct.pack(
        "<HBBBBBB", 2024, 1, 15, 10, 30, 45, 1
    )  # year, month, day, hour, min, sec, valid
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=41, cmd_id=CMD_REQUEST_SYSTEM_TIME, data=payload
    ).to_bytes()


@pytest.fixture
def frame_single_axis_attitude_ack() -> bytes:
    """Single axis attitude ACK frame (0x41) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=42, cmd_id=CMD_SINGLE_AXIS_ATTITUDE, data=payload
    ).to_bytes()


@pytest.fixture
def frame_sd_format_ack() -> bytes:
    """SD format ACK frame (0x48) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(ctrl=CTRL_ACK_PACK, seq=43, cmd_id=CMD_SD_FORMAT, data=payload).to_bytes()


@pytest.fixture
def frame_pic_name_type_ack() -> bytes:
    """Picture name type ACK frame (0x49) — DATE_TIME format."""
    payload = struct.pack("<B", 0)
    return Frame(ctrl=CTRL_ACK_PACK, seq=44, cmd_id=CMD_GET_PIC_NAME_TYPE, data=payload).to_bytes()


@pytest.fixture
def frame_set_pic_name_type_ack() -> bytes:
    """Set picture name type ACK frame (0x4A) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(ctrl=CTRL_ACK_PACK, seq=45, cmd_id=CMD_SET_PIC_NAME_TYPE, data=payload).to_bytes()


@pytest.fixture
def frame_mavlink_osd_flag_ack() -> bytes:
    """MAVLink OSD flag ACK frame (0x4B) — enabled."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=46, cmd_id=CMD_GET_MAVLINK_OSD_FLAG, data=payload
    ).to_bytes()


@pytest.fixture
def frame_set_mavlink_osd_flag_ack() -> bytes:
    """Set MAVLink OSD flag ACK frame (0x4C) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=47, cmd_id=CMD_SET_MAVLINK_OSD_FLAG, data=payload
    ).to_bytes()


@pytest.fixture
def frame_ai_track_stream_push() -> bytes:
    """AI track stream push frame (0x50)."""
    # target_type, x, y, w, h, reserved
    payload = struct.pack("<HHHHHH", 1, 640, 360, 200, 150, 0)
    return Frame(ctrl=CTRL_NEED_ACK, seq=48, cmd_id=CMD_AI_TRACK_STREAM, data=payload).to_bytes()


@pytest.fixture
def frame_ai_track_stream_sta_ack() -> bytes:
    """AI track stream status ACK frame (0x4E) — enabled."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=49, cmd_id=CMD_GET_AI_TRACK_STREAM_STA, data=payload
    ).to_bytes()


@pytest.fixture
def frame_set_ai_track_stream_sta_ack() -> bytes:
    """Set AI track stream status ACK frame (0x51) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=50, cmd_id=CMD_SET_AI_TRACK_STREAM_STA, data=payload
    ).to_bytes()


@pytest.fixture
def frame_weak_control_mode_ack() -> bytes:
    """Weak control mode ACK frame (0x70) — OPEN_LOOP."""
    payload = struct.pack("<B", 0)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=51, cmd_id=CMD_REQUEST_WEAK_CONTROL_MODE, data=payload
    ).to_bytes()


@pytest.fixture
def frame_set_weak_control_mode_ack() -> bytes:
    """Set weak control mode ACK frame (0x71) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(
        ctrl=CTRL_ACK_PACK, seq=52, cmd_id=CMD_SET_WEAK_CONTROL_MODE, data=payload
    ).to_bytes()


@pytest.fixture
def frame_soft_reboot_ack() -> bytes:
    """Soft reboot ACK frame (0x80) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(ctrl=CTRL_ACK_PACK, seq=53, cmd_id=CMD_SOFT_REBOOT, data=payload).to_bytes()


@pytest.fixture
def frame_get_ip_ack() -> bytes:
    """Get IP ACK frame (0x81) — 192.168.144.25."""
    payload = bytes([192, 168, 144, 25])
    return Frame(ctrl=CTRL_ACK_PACK, seq=54, cmd_id=CMD_GET_IP, data=payload).to_bytes()


@pytest.fixture
def frame_set_ip_ack() -> bytes:
    """Set IP ACK frame (0x82) with sta=1."""
    payload = struct.pack("<B", 1)
    return Frame(ctrl=CTRL_ACK_PACK, seq=55, cmd_id=CMD_SET_IP, data=payload).to_bytes()
