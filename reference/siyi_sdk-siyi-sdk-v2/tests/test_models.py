# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for siyi_sdk.models module."""

from __future__ import annotations

from dataclasses import fields
from ipaddress import IPv4Address

import pytest

from siyi_sdk import models


class TestProductID:
    """Test ProductID enumeration."""

    def test_zr10(self):
        """ZR10 should have value 0x6B."""
        assert models.ProductID.ZR10 == 0x6B
        assert models.ProductID(0x6B).name == "ZR10"

    def test_a8_mini(self):
        """A8_MINI should have value 0x73."""
        assert models.ProductID.A8_MINI == 0x73
        assert models.ProductID(0x73).name == "A8_MINI"

    def test_a2_mini(self):
        """A2_MINI should have value 0x75."""
        assert models.ProductID.A2_MINI == 0x75
        assert models.ProductID(0x75).name == "A2_MINI"

    def test_zr30(self):
        """ZR30 should have value 0x78."""
        assert models.ProductID.ZR30 == 0x78
        assert models.ProductID(0x78).name == "ZR30"

    def test_quad_spectrum(self):
        """QUAD_SPECTRUM should have value 0x7A."""
        assert models.ProductID.QUAD_SPECTRUM == 0x7A
        assert models.ProductID(0x7A).name == "QUAD_SPECTRUM"


class TestGimbalMotionMode:
    """Test GimbalMotionMode enumeration."""

    def test_values(self):
        """GimbalMotionMode values should match spec."""
        assert models.GimbalMotionMode.LOCK == 0
        assert models.GimbalMotionMode.FOLLOW == 1
        assert models.GimbalMotionMode.FPV == 2


class TestMountingDirection:
    """Test MountingDirection enumeration."""

    def test_values(self):
        """MountingDirection values should match spec."""
        assert models.MountingDirection.RESERVED == 0
        assert models.MountingDirection.NORMAL == 1
        assert models.MountingDirection.INVERTED == 2


class TestHDMICVBSOutput:
    """Test HDMICVBSOutput enumeration."""

    def test_values(self):
        """HDMICVBSOutput values should match spec."""
        assert models.HDMICVBSOutput.HDMI_ON_CVBS_OFF == 0
        assert models.HDMICVBSOutput.HDMI_OFF_CVBS_ON == 1


class TestRecordingState:
    """Test RecordingState enumeration."""

    def test_values(self):
        """RecordingState values should match spec."""
        assert models.RecordingState.NOT_RECORDING == 0
        assert models.RecordingState.RECORDING == 1
        assert models.RecordingState.NO_TF_CARD == 2
        assert models.RecordingState.DATA_LOSS == 3


class TestFunctionFeedback:
    """Test FunctionFeedback enumeration."""

    def test_values(self):
        """FunctionFeedback values should match spec."""
        assert models.FunctionFeedback.PHOTO_OK == 0
        assert models.FunctionFeedback.PHOTO_FAILED == 1
        assert models.FunctionFeedback.HDR_ON == 2
        assert models.FunctionFeedback.HDR_OFF == 3
        assert models.FunctionFeedback.RECORDING_FAILED == 4
        assert models.FunctionFeedback.RECORDING_STARTED == 5
        assert models.FunctionFeedback.RECORDING_STOPPED == 6


class TestCaptureFuncType:
    """Test CaptureFuncType enumeration."""

    def test_values(self):
        """CaptureFuncType values should match spec."""
        assert models.CaptureFuncType.PHOTO == 0
        assert models.CaptureFuncType.HDR_TOGGLE == 1
        assert models.CaptureFuncType.START_RECORD == 2
        assert models.CaptureFuncType.LOCK_MODE == 3
        assert models.CaptureFuncType.FOLLOW_MODE == 4
        assert models.CaptureFuncType.FPV_MODE == 5
        assert models.CaptureFuncType.ENABLE_HDMI == 6
        assert models.CaptureFuncType.ENABLE_CVBS == 7
        assert models.CaptureFuncType.DISABLE_HDMI_CVBS == 8
        assert models.CaptureFuncType.TILT_DOWNWARD == 9
        assert models.CaptureFuncType.ZOOM_LINKAGE == 10


class TestCenteringAction:
    """Test CenteringAction enumeration."""

    def test_values(self):
        """CenteringAction values should match spec."""
        assert models.CenteringAction.ONE_KEY_CENTER == 1
        assert models.CenteringAction.CENTER_DOWNWARD == 2
        assert models.CenteringAction.CENTER == 3
        assert models.CenteringAction.DOWNWARD == 4


class TestVideoEncType:
    """Test VideoEncType enumeration."""

    def test_values(self):
        """VideoEncType values should match spec."""
        assert models.VideoEncType.H264 == 1
        assert models.VideoEncType.H265 == 2


class TestStreamType:
    """Test StreamType enumeration."""

    def test_values(self):
        """StreamType values should match spec."""
        assert models.StreamType.RECORDING == 0
        assert models.StreamType.MAIN == 1
        assert models.StreamType.SUB == 2


class TestVideoStitchingMode:
    """Test VideoStitchingMode enumeration."""

    def test_values(self):
        """VideoStitchingMode should have 9 modes (0-8)."""
        assert models.VideoStitchingMode.MODE_0 == 0
        assert models.VideoStitchingMode.MODE_1 == 1
        assert models.VideoStitchingMode.MODE_2 == 2
        assert models.VideoStitchingMode.MODE_3 == 3
        assert models.VideoStitchingMode.MODE_4 == 4
        assert models.VideoStitchingMode.MODE_5 == 5
        assert models.VideoStitchingMode.MODE_6 == 6
        assert models.VideoStitchingMode.MODE_7 == 7
        assert models.VideoStitchingMode.MODE_8 == 8


class TestPseudoColor:
    """Test PseudoColor enumeration."""

    def test_values(self):
        """PseudoColor values should match spec."""
        assert models.PseudoColor.WHITE_HOT == 0
        assert models.PseudoColor.RESERVED == 1
        assert models.PseudoColor.SEPIA == 2
        assert models.PseudoColor.IRONBOW == 3
        assert models.PseudoColor.RAINBOW == 4
        assert models.PseudoColor.NIGHT == 5
        assert models.PseudoColor.AURORA == 6
        assert models.PseudoColor.RED_HOT == 7
        assert models.PseudoColor.JUNGLE == 8
        assert models.PseudoColor.MEDICAL == 9
        assert models.PseudoColor.BLACK_HOT == 10
        assert models.PseudoColor.GLORY_HOT == 11


class TestTempMeasureFlag:
    """Test TempMeasureFlag enumeration."""

    def test_values(self):
        """TempMeasureFlag values should match spec."""
        assert models.TempMeasureFlag.DISABLE == 0
        assert models.TempMeasureFlag.MEASURE_ONCE == 1
        assert models.TempMeasureFlag.CONTINUOUS_5HZ == 2


class TestThermalOutputMode:
    """Test ThermalOutputMode enumeration."""

    def test_values(self):
        """ThermalOutputMode values should match spec."""
        assert models.ThermalOutputMode.FPS30 == 0
        assert models.ThermalOutputMode.FPS25_PLUS_TEMP == 1


class TestThermalGain:
    """Test ThermalGain enumeration."""

    def test_values(self):
        """ThermalGain values should match spec."""
        assert models.ThermalGain.LOW == 0
        assert models.ThermalGain.HIGH == 1


class TestIRThreshPrecision:
    """Test IRThreshPrecision enumeration."""

    def test_values(self):
        """IRThreshPrecision values should match spec."""
        assert models.IRThreshPrecision.MAX == 1
        assert models.IRThreshPrecision.MID == 2
        assert models.IRThreshPrecision.MIN == 3


class TestFCDataType:
    """Test FCDataType enumeration."""

    def test_values(self):
        """FCDataType values should match spec."""
        assert models.FCDataType.ATTITUDE == 1
        assert models.FCDataType.RC_CHANNELS == 2


class TestGimbalDataType:
    """Test GimbalDataType enumeration."""

    def test_values(self):
        """GimbalDataType values should match spec."""
        assert models.GimbalDataType.ATTITUDE == 1
        assert models.GimbalDataType.LASER_RANGE == 2
        assert models.GimbalDataType.MAGNETIC_ENCODER == 3
        assert models.GimbalDataType.MOTOR_VOLTAGE == 4


class TestDataStreamFreq:
    """Test DataStreamFreq enumeration."""

    def test_values(self):
        """DataStreamFreq values should match spec."""
        assert models.DataStreamFreq.OFF == 0
        assert models.DataStreamFreq.HZ2 == 1
        assert models.DataStreamFreq.HZ4 == 2
        assert models.DataStreamFreq.HZ5 == 3
        assert models.DataStreamFreq.HZ10 == 4
        assert models.DataStreamFreq.HZ20 == 5
        assert models.DataStreamFreq.HZ50 == 6
        assert models.DataStreamFreq.HZ100 == 7


class TestControlMode:
    """Test ControlMode enumeration."""

    def test_values(self):
        """ControlMode values should match spec."""
        assert models.ControlMode.ATTITUDE == 0
        assert models.ControlMode.WEAK == 1
        assert models.ControlMode.MIDDLE == 2
        assert models.ControlMode.FPV == 3
        assert models.ControlMode.MOTOR_CLOSE == 4


class TestAITargetID:
    """Test AITargetID enumeration."""

    def test_values(self):
        """AITargetID values should match spec."""
        assert models.AITargetID.HUMAN == 0
        assert models.AITargetID.CAR == 1
        assert models.AITargetID.BUS == 2
        assert models.AITargetID.TRUCK == 3
        assert models.AITargetID.ANY == 255


class TestAITrackStatus:
    """Test AITrackStatus enumeration."""

    def test_values(self):
        """AITrackStatus values should match spec."""
        assert models.AITrackStatus.NORMAL_AI == 0
        assert models.AITrackStatus.INTERMITTENT_LOSS == 1
        assert models.AITrackStatus.LOST == 2
        assert models.AITrackStatus.USER_CANCELED == 3
        assert models.AITrackStatus.NORMAL_ANY == 4


class TestAIStreamStatus:
    """Test AIStreamStatus enumeration."""

    def test_values(self):
        """AIStreamStatus values should match spec."""
        assert models.AIStreamStatus.DISABLED == 0
        assert models.AIStreamStatus.STREAMING == 1
        assert models.AIStreamStatus.AI_NOT_ENABLED == 2
        assert models.AIStreamStatus.TRACKING_NOT_ENABLED == 3


class TestFileType:
    """Test FileType enumeration."""

    def test_values(self):
        """FileType values should match spec."""
        assert models.FileType.PICTURE == 0
        assert models.FileType.TEMP_RAW == 1
        assert models.FileType.RECORD_VIDEO == 2


class TestFileNameType:
    """Test FileNameType enumeration."""

    def test_values(self):
        """FileNameType values should match spec."""
        assert models.FileNameType.RESERVE == 0
        assert models.FileNameType.INDEX == 1
        assert models.FileNameType.TIMESTAMP == 2

    def test_picname_alias(self):
        """PicName should be an alias for FileNameType."""
        assert models.PicName is models.FileNameType


class TestFirmwareVersion:
    """Test FirmwareVersion dataclass."""

    def test_frozen(self):
        """FirmwareVersion should be frozen."""
        fw = models.FirmwareVersion(camera=1, gimbal=2, zoom=3)
        with pytest.raises(AttributeError):
            fw.camera = 4  # type: ignore

    def test_slots(self):
        """FirmwareVersion should have slots."""
        assert hasattr(models.FirmwareVersion, "__slots__")

    def test_decode_word(self):
        """decode_word should extract major.minor.patch from word."""
        # Example from spec: 0x6E030203 -> v3.2.3 (high byte 0x6E ignored)
        # Actually: patch=3, minor=2, major=3 for 0x030203
        major, minor, patch = models.FirmwareVersion.decode_word(0x6E030203)
        assert major == 3
        assert minor == 2
        assert patch == 3

    def test_decode_word_simple(self):
        """decode_word with simple version number."""
        major, minor, patch = models.FirmwareVersion.decode_word(0x00010203)
        assert major == 1
        assert minor == 2
        assert patch == 3


class TestHardwareID:
    """Test HardwareID dataclass."""

    def test_frozen(self):
        """HardwareID should be frozen."""
        hw = models.HardwareID(raw=b"6b" + b"\x00" * 10)
        with pytest.raises(AttributeError):
            hw.raw = b"test"  # type: ignore

    def test_slots(self):
        """HardwareID should have slots."""
        assert hasattr(models.HardwareID, "__slots__")

    def test_product_id_zr10(self):
        """product_id property should return ProductID for ZR10."""
        hw = models.HardwareID(raw=b"6b" + b"\x00" * 10)
        assert hw.product_id == models.ProductID.ZR10

    def test_product_id_a8_mini(self):
        """product_id property should return ProductID for A8_MINI."""
        hw = models.HardwareID(raw=b"73" + b"\x00" * 10)
        assert hw.product_id == models.ProductID.A8_MINI


class TestZoomRange:
    """Test ZoomRange dataclass."""

    def test_max_zoom_property(self):
        """max_zoom property should combine integer and decimal parts."""
        zr = models.ZoomRange(max_int=30, max_float=5)
        assert zr.max_zoom == 30.5

    def test_max_zoom_whole(self):
        """max_zoom with zero decimal part."""
        zr = models.ZoomRange(max_int=10, max_float=0)
        assert zr.max_zoom == 10.0


class TestCurrentZoom:
    """Test CurrentZoom dataclass."""

    def test_zoom_property(self):
        """zoom property should combine integer and decimal parts."""
        cz = models.CurrentZoom(integer=5, decimal=3)
        assert cz.zoom == 5.3

    def test_zoom_whole(self):
        """zoom with zero decimal part."""
        cz = models.CurrentZoom(integer=10, decimal=0)
        assert cz.zoom == 10.0


class TestAngleLimits:
    """Test AngleLimits dataclass and ANGLE_LIMITS table."""

    def test_angle_limits_has_all_products(self):
        """ANGLE_LIMITS should have entry for every ProductID."""
        for product in models.ProductID:
            assert product in models.ANGLE_LIMITS, f"Missing {product.name}"

    def test_zr10_limits(self):
        """ZR10 angle limits should match spec."""
        limits = models.ANGLE_LIMITS[models.ProductID.ZR10]
        assert limits.yaw_min == -135.0
        assert limits.yaw_max == 135.0
        assert limits.pitch_min == -90.0
        assert limits.pitch_max == 25.0

    def test_a8_mini_limits(self):
        """A8_MINI angle limits should match spec (same as ZR10)."""
        limits = models.ANGLE_LIMITS[models.ProductID.A8_MINI]
        assert limits.yaw_min == -135.0
        assert limits.yaw_max == 135.0
        assert limits.pitch_min == -90.0
        assert limits.pitch_max == 25.0

    def test_zr30_limits(self):
        """ZR30 angle limits should match spec."""
        limits = models.ANGLE_LIMITS[models.ProductID.ZR30]
        assert limits.yaw_min == -270.0
        assert limits.yaw_max == 270.0
        assert limits.pitch_min == -90.0
        assert limits.pitch_max == 25.0

    def test_a2_mini_limits(self):
        """A2_MINI angle limits (fixed yaw)."""
        limits = models.ANGLE_LIMITS[models.ProductID.A2_MINI]
        assert limits.yaw_min == 0.0
        assert limits.yaw_max == 0.0
        assert limits.pitch_min == -90.0
        assert limits.pitch_max == 25.0

    def test_quad_spectrum_limits(self):
        """QUAD_SPECTRUM angle limits (unlimited yaw)."""
        limits = models.ANGLE_LIMITS[models.ProductID.QUAD_SPECTRUM]
        assert limits.yaw_min == -360.0
        assert limits.yaw_max == 360.0
        assert limits.pitch_min == -90.0
        assert limits.pitch_max == 25.0


_DATACLASSES = [
    models.FirmwareVersion,
    models.HardwareID,
    models.CameraSystemInfo,
    models.GimbalAttitude,
    models.SetAttitudeAck,
    models.AircraftAttitude,
    models.RCChannels,
    models.EncodingParams,
    models.TempPoint,
    models.TempRegion,
    models.TempGlobal,
    models.EnvCorrectionParams,
    models.LaserDistance,
    models.LaserTargetLatLon,
    models.ZoomRange,
    models.CurrentZoom,
    models.RawGPS,
    models.MagneticEncoderAngles,
    models.MotorVoltage,
    models.WeakControlThreshold,
    models.SystemTime,
    models.GimbalSystemInfo,
    models.IRThreshRegion,
    models.IRThreshParams,
    models.AITrackingTarget,
    models.IPConfig,
    models.AngleLimits,
]


class TestDataclassProperties:
    """Test that all dataclasses have required properties."""

    @pytest.mark.parametrize("cls", _DATACLASSES)
    def test_has_slots(self, cls):
        """Dataclass should have __slots__."""
        assert hasattr(cls, "__slots__"), f"{cls.__name__} missing __slots__"

    @pytest.mark.parametrize("cls", _DATACLASSES)
    def test_is_frozen(self, cls):
        """Dataclass should be frozen (immutable)."""
        # Get field info to create an instance
        field_info = fields(cls)
        # Create dummy values for each field
        values = {}
        for field in field_info:
            if field.type == "int" or field.type is int:
                values[field.name] = 0
            elif field.type == "float" or field.type is float:
                values[field.name] = 0.0
            elif field.type == "bytes" or field.type is bytes:
                values[field.name] = b""
            elif field.type == "bool" or field.type is bool:
                values[field.name] = False
            elif "tuple" in str(field.type):
                values[field.name] = ()
            elif field.type == "IPv4Address" or field.type is IPv4Address:
                values[field.name] = IPv4Address("0.0.0.0")
            elif field.type == "float | None":
                values[field.name] = None
            elif hasattr(models, str(field.type).split(".")[-1].strip("'")):
                # It's an enum or dataclass - use first value or create instance
                type_name = str(field.type).split(".")[-1].strip("'")
                type_cls = getattr(models, type_name, None)
                if type_cls and hasattr(type_cls, "__members__"):
                    # It's an enum
                    values[field.name] = next(iter(type_cls.__members__.values()))
                elif type_cls:
                    # It's a dataclass - skip this test for nested dataclasses
                    pytest.skip(f"Skipping nested dataclass test for {cls.__name__}")
                else:
                    values[field.name] = 0
            else:
                values[field.name] = 0

        instance = cls(**values)
        first_field = field_info[0].name

        with pytest.raises(AttributeError):
            setattr(instance, first_field, values[first_field])
