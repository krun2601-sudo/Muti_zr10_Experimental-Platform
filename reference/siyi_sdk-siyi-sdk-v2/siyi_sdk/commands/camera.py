# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Camera command encoders/decoders (0x0A, 0x0B, 0x0C, 0x20, 0x21, 0x48-0x4C).

This module implements encoding/decoding for camera control commands including:
- Camera system info
- Function feedback
- Capture photo / record video
- Encoding parameters
- SD card format
- Picture naming
- HDMI OSD flag
"""

from __future__ import annotations

import struct

from siyi_sdk.constants import (
    CMD_FUNCTION_FEEDBACK,
    CMD_GET_MAVLINK_OSD_FLAG,
    CMD_GET_PIC_NAME_TYPE,
    CMD_REQUEST_CAMERA_SYSTEM_INFO,
    CMD_REQUEST_ENCODING_PARAMS,
    CMD_SD_FORMAT,
    CMD_SET_ENCODING_PARAMS,
    CMD_SET_MAVLINK_OSD_FLAG,
    CMD_SET_PIC_NAME_TYPE,
)
from siyi_sdk.exceptions import ConfigurationError, MalformedPayloadError, ResponseError
from siyi_sdk.models import (
    CameraSystemInfo,
    CaptureFuncType,
    EncodingParams,
    FileNameType,
    FileType,
    FunctionFeedback,
    GimbalMotionMode,
    HDMICVBSOutput,
    MountingDirection,
    RecordingState,
    StreamType,
    VideoEncType,
)


def encode_camera_system_info() -> bytes:
    """Encode camera system info request (0x0A).

    Returns:
        Empty payload.

    """
    return b""


def decode_camera_system_info(payload: bytes) -> CameraSystemInfo:
    """Decode camera system info response (0x0A).

    Args:
        payload: 7 or 8 bytes. Cameras without optical zoom (e.g. A8 Mini)
            return 7 bytes (no zoom_linkage field); zoom_linkage defaults to 0.

    Returns:
        CameraSystemInfo dataclass.

    Raises:
        MalformedPayloadError: If payload length is not 7 or 8 bytes.

    """
    if len(payload) not in (7, 8):
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_CAMERA_SYSTEM_INFO,
            reason=f"expected 7 or 8 bytes, got {len(payload)}",
        )
    zoom_linkage = 0
    if len(payload) == 8:
        (
            reserved_a,
            hdr_sta,
            reserved_b,
            record_sta,
            gimbal_motion_mode,
            gimbal_mounting_dir,
            video_hdmi_or_cvbs,
            zoom_linkage,
        ) = struct.unpack("<BBBBBBBB", payload)
    else:
        (
            reserved_a,
            hdr_sta,
            reserved_b,
            record_sta,
            gimbal_motion_mode,
            gimbal_mounting_dir,
            video_hdmi_or_cvbs,
        ) = struct.unpack("<BBBBBBB", payload)
    return CameraSystemInfo(
        reserved_a=reserved_a,
        hdr_sta=hdr_sta,
        reserved_b=reserved_b,
        record_sta=RecordingState(record_sta),
        gimbal_motion_mode=GimbalMotionMode(gimbal_motion_mode),
        gimbal_mounting_dir=MountingDirection(gimbal_mounting_dir),
        video_hdmi_or_cvbs=HDMICVBSOutput(video_hdmi_or_cvbs),
        zoom_linkage=zoom_linkage,
    )


def decode_function_feedback(payload: bytes) -> FunctionFeedback:
    """Decode function feedback response (0x0B).

    Args:
        payload: 1-byte feedback code.

    Returns:
        FunctionFeedback enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_FUNCTION_FEEDBACK,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (info_type,) = struct.unpack("<B", payload)
    return FunctionFeedback(info_type)


def encode_capture(func: CaptureFuncType) -> bytes:
    """Encode capture photo / record video request (0x0C).

    Args:
        func: Function type (0-10).

    Returns:
        1-byte payload (uint8).

    Raises:
        ConfigurationError: If func is not a valid CaptureFuncType.

    """
    if not isinstance(func, CaptureFuncType):
        raise ConfigurationError(f"func must be a CaptureFuncType, got {func}")
    return struct.pack("<B", func)


def encode_get_encoding_params(stream: StreamType) -> bytes:
    """Encode get encoding params request (0x20).

    Args:
        stream: Stream type (0=recording, 1=main, 2=sub).

    Returns:
        1-byte payload (uint8).

    Raises:
        ConfigurationError: If stream is not a valid StreamType.

    """
    if not isinstance(stream, StreamType):
        raise ConfigurationError(f"stream must be a StreamType, got {stream}")
    return struct.pack("<B", stream)


def decode_get_encoding_params(payload: bytes) -> EncodingParams:
    """Decode get encoding params response (0x20).

    Args:
        payload: 9 bytes.

    Returns:
        EncodingParams dataclass.

    Raises:
        MalformedPayloadError: If payload length is not 9 bytes.

    """
    if len(payload) != 9:
        raise MalformedPayloadError(
            cmd_id=CMD_REQUEST_ENCODING_PARAMS,
            reason=f"expected 9 bytes, got {len(payload)}",
        )
    stream_type, enc_type, res_l, res_h, bitrate, frame_rate = struct.unpack("<BBHHHB", payload)
    return EncodingParams(
        stream_type=StreamType(stream_type),
        enc_type=VideoEncType(enc_type),
        resolution_w=res_l,
        resolution_h=res_h,
        bitrate_kbps=bitrate,
        frame_rate=frame_rate,
    )


def encode_set_encoding_params(params: EncodingParams) -> bytes:
    """Encode set encoding params request (0x21).

    Args:
        params: EncodingParams dataclass.

    Returns:
        9-byte payload (uint8 + uint8 + 2xuint16 LE + uint16 LE + uint8 reserve).

    Raises:
        ConfigurationError: If resolution is not 1920x1080 or 1280x720.

    """
    # Validate resolution
    if (params.resolution_w, params.resolution_h) not in ((1920, 1080), (1280, 720)):
        raise ConfigurationError(
            f"resolution must be 1920x1080 or 1280x720, got "
            f"{params.resolution_w}x{params.resolution_h}"
        )
    return struct.pack(
        "<BBHHHB",
        params.stream_type,
        params.enc_type,
        params.resolution_w,
        params.resolution_h,
        params.bitrate_kbps,
        0,  # reserve byte
    )


def decode_set_encoding_params_ack(payload: bytes) -> bool:
    """Decode set encoding params acknowledgment (0x21).

    Args:
        payload: 2 bytes (stream_type, sta).

    Returns:
        True if successful.

    Raises:
        MalformedPayloadError: If payload length is not 2 bytes.
        ResponseError: If status is 0 (failure).

    """
    if len(payload) != 2:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_ENCODING_PARAMS,
            reason=f"expected 2 bytes, got {len(payload)}",
        )
    _stream_type, sta = struct.unpack("<BB", payload)
    if sta == 0:
        raise ResponseError(cmd_id=CMD_SET_ENCODING_PARAMS, sta=sta)
    return True


def encode_format_sd(format_sta: int = 1) -> bytes:
    """Encode SD card format request (0x48).

    Args:
        format_sta: Format command (1=format).

    Returns:
        1-byte payload (uint8).

    """
    return struct.pack("<B", format_sta)


def decode_format_sd_ack(payload: bytes) -> bool:
    """Decode SD card format acknowledgment (0x48).

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
            cmd_id=CMD_SD_FORMAT,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (ack,) = struct.unpack("<B", payload)
    if ack == 0:
        raise ResponseError(cmd_id=CMD_SD_FORMAT, sta=ack)
    return True


def encode_get_pic_name_type(ft: FileType) -> bytes:
    """Encode get picture name type request (0x49).

    Args:
        ft: File type.

    Returns:
        1-byte payload (uint8).

    Raises:
        ConfigurationError: If ft is not a valid FileType.

    """
    if not isinstance(ft, FileType):
        raise ConfigurationError(f"ft must be a FileType, got {ft}")
    return struct.pack("<B", ft)


def decode_get_pic_name_type(payload: bytes) -> FileNameType:
    """Decode get picture name type response (0x49).

    Args:
        payload: 2 bytes (file_type, file_name_type).

    Returns:
        FileNameType enumeration value.

    Raises:
        MalformedPayloadError: If payload length is not 2 bytes.

    """
    if len(payload) != 2:
        raise MalformedPayloadError(
            cmd_id=CMD_GET_PIC_NAME_TYPE,
            reason=f"expected 2 bytes, got {len(payload)}",
        )
    _file_type, file_name_type = struct.unpack("<BB", payload)
    return FileNameType(file_name_type)


def encode_set_pic_name_type(ft: FileType, nt: FileNameType) -> bytes:
    """Encode set picture name type request (0x4A).

    Args:
        ft: File type.
        nt: File name type.

    Returns:
        2-byte payload (2 x uint8).

    Raises:
        ConfigurationError: If ft or nt are not valid enum values.

    """
    if not isinstance(ft, FileType):
        raise ConfigurationError(f"ft must be a FileType, got {ft}")
    if not isinstance(nt, FileNameType):
        raise ConfigurationError(f"nt must be a FileNameType, got {nt}")
    return struct.pack("<BB", ft, nt)


def decode_set_pic_name_type_ack(payload: bytes) -> None:
    """Decode set picture name type acknowledgment (0x4A).

    Args:
        payload: 2 bytes (file_type, file_name_type).

    Raises:
        MalformedPayloadError: If payload length is not 2 bytes.

    """
    if len(payload) != 2:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_PIC_NAME_TYPE,
            reason=f"expected 2 bytes, got {len(payload)}",
        )
    # No further validation needed; successful response echoes the request


def encode_get_osd_flag() -> bytes:
    """Encode get HDMI OSD flag request (0x4B).

    Returns:
        Empty payload.

    """
    return b""


def decode_get_osd_flag(payload: bytes) -> bool:
    """Decode get HDMI OSD flag response (0x4B).

    Args:
        payload: 1-byte OSD status.

    Returns:
        True if OSD is enabled.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_GET_MAVLINK_OSD_FLAG,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (osd_sta,) = struct.unpack("<B", payload)
    return bool(osd_sta)


def encode_set_osd_flag(on: bool) -> bytes:
    """Encode set HDMI OSD flag request (0x4C).

    Args:
        on: True to enable OSD.

    Returns:
        1-byte payload (uint8).

    """
    return struct.pack("<B", int(on))


def decode_set_osd_flag_ack(payload: bytes) -> bool:
    """Decode set HDMI OSD flag acknowledgment (0x4C).

    Args:
        payload: 1-byte OSD status.

    Returns:
        True if OSD is now enabled.

    Raises:
        MalformedPayloadError: If payload length is not 1 byte.

    """
    if len(payload) != 1:
        raise MalformedPayloadError(
            cmd_id=CMD_SET_MAVLINK_OSD_FLAG,
            reason=f"expected 1 byte, got {len(payload)}",
        )
    (osd_sta,) = struct.unpack("<B", payload)
    return bool(osd_sta)
