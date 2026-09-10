# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for siyi_sdk.protocol.frame module."""

from __future__ import annotations

import pytest

from siyi_sdk.constants import CTRL_NEED_ACK
from siyi_sdk.exceptions import CRCError, FramingError
from siyi_sdk.protocol.frame import Frame


class TestFrameBasic:
    """Test basic Frame properties."""

    def test_data_len_property(self):
        """data_len should return length of data."""
        frame = Frame(ctrl=1, seq=0, cmd_id=0, data=b"hello")
        assert frame.data_len == 5

    def test_data_len_empty(self):
        """data_len should be 0 for empty data."""
        frame = Frame(ctrl=1, seq=0, cmd_id=0, data=b"")
        assert frame.data_len == 0

    def test_frame_is_frozen(self):
        """Frame should be immutable."""
        frame = Frame(ctrl=1, seq=0, cmd_id=0, data=b"")
        with pytest.raises(AttributeError):
            frame.ctrl = 2  # type: ignore

    def test_frame_has_slots(self):
        """Frame should have slots."""
        assert hasattr(Frame, "__slots__")


class TestFrameToBytes:
    """Test Frame.to_bytes() serialization."""

    def test_heartbeat_frame(self):
        """Heartbeat frame should serialize correctly."""
        frame = Frame(ctrl=1, seq=0, cmd_id=0x00, data=b"\x00")
        result = frame.to_bytes()
        # Expected: 55 66 01 01 00 00 00 00 00 59 8B
        expected = bytes.fromhex("556601010000000000598B")
        assert result == expected

    def test_zoom_plus_one(self):
        """Zoom +1 frame should serialize correctly."""
        frame = Frame(ctrl=1, seq=0, cmd_id=0x05, data=b"\x01")
        result = frame.to_bytes()
        # Expected: 55 66 01 01 00 00 00 05 01 8d 64
        expected = bytes.fromhex("5566010100000005018d64")
        assert result == expected

    def test_take_photo(self):
        """Take photo frame should serialize correctly."""
        frame = Frame(ctrl=1, seq=0, cmd_id=0x0C, data=b"\x00")
        result = frame.to_bytes()
        # Expected: 55 66 01 01 00 00 00 0c 00 34 ce (11 bytes)
        expected = bytes.fromhex("556601010000000c0034ce")
        assert result == expected

    def test_pan_tilt_100_100(self):
        """Pan/Tilt 100,100 frame should serialize correctly."""
        frame = Frame(ctrl=1, seq=0, cmd_id=0x07, data=b"\x64\x64")
        result = frame.to_bytes()
        # Expected: 55 66 01 02 00 00 00 07 64 64 3d cf
        expected = bytes.fromhex("55660102000000076464 3dcf".replace(" ", ""))
        assert result == expected

    def test_one_key_centering(self):
        """One-key centering frame should serialize correctly."""
        frame = Frame(ctrl=1, seq=0, cmd_id=0x08, data=b"\x01")
        result = frame.to_bytes()
        # Expected: 55 66 01 01 00 00 00 08 01 d1 12
        expected = bytes.fromhex("556601010000000801d112")
        assert result == expected

    def test_firmware_version_request(self):
        """Firmware version request should serialize correctly."""
        # Note: spec example shows CTRL=1 for this request (ack_pack bit set)
        frame = Frame(ctrl=1, seq=0, cmd_id=0x01, data=b"")
        result = frame.to_bytes()
        # Expected: 55 66 01 00 00 00 00 01 64 c4
        expected = bytes.fromhex("5566010000000001 64c4".replace(" ", ""))
        assert result == expected

    def test_hardware_id_request(self):
        """Hardware ID request should serialize correctly."""
        # Spec example shows CTRL=1 for this request
        frame = Frame(ctrl=1, seq=0, cmd_id=0x02, data=b"")
        result = frame.to_bytes()
        # Expected: 55 66 01 00 00 00 00 02 07 f4
        expected = bytes.fromhex("556601000000000207f4")
        assert result == expected

    def test_sequence_number(self):
        """Sequence number should be encoded little-endian."""
        frame = Frame(ctrl=1, seq=0x1234, cmd_id=0x00, data=b"")
        result = frame.to_bytes()
        # SEQ is at offset 5-6 (little-endian)
        assert result[5:7] == b"\x34\x12"


class TestFrameFromBytes:
    """Test Frame.from_bytes() deserialization."""

    def test_heartbeat_frame(self):
        """Heartbeat frame should deserialize correctly."""
        data = bytes.fromhex("556601010000000000598B")
        frame = Frame.from_bytes(data)
        assert frame.ctrl == 1
        assert frame.seq == 0
        assert frame.cmd_id == 0x00
        assert frame.data == b"\x00"

    def test_zoom_plus_one(self):
        """Zoom +1 frame should deserialize correctly."""
        data = bytes.fromhex("5566010100000005018d64")
        frame = Frame.from_bytes(data)
        assert frame.ctrl == 1
        assert frame.seq == 0
        assert frame.cmd_id == 0x05
        assert frame.data == b"\x01"

    def test_take_photo(self):
        """Take photo frame should deserialize correctly."""
        data = bytes.fromhex("556601010000000c0034ce")
        frame = Frame.from_bytes(data)
        assert frame.ctrl == 1
        assert frame.seq == 0
        assert frame.cmd_id == 0x0C
        assert frame.data == b"\x00"

    def test_pan_tilt_100_100(self):
        """Pan/Tilt 100,100 frame should deserialize correctly."""
        data = bytes.fromhex("556601020000000764643dcf")
        frame = Frame.from_bytes(data)
        assert frame.ctrl == 1
        assert frame.seq == 0
        assert frame.cmd_id == 0x07
        assert frame.data == b"\x64\x64"

    def test_roundtrip(self):
        """Frame should survive to_bytes/from_bytes roundtrip."""
        original = Frame(ctrl=1, seq=0x1234, cmd_id=0x42, data=b"test data")
        wire = original.to_bytes()
        restored = Frame.from_bytes(wire)
        assert restored.ctrl == original.ctrl
        assert restored.seq == original.seq
        assert restored.cmd_id == original.cmd_id
        assert restored.data == original.data


class TestFrameFromBytesErrors:
    """Test Frame.from_bytes() error handling."""

    def test_too_short(self):
        """Frame too short should raise FramingError."""
        data = bytes.fromhex("5566010100")  # 5 bytes, need at least 10
        with pytest.raises(FramingError):
            Frame.from_bytes(data)

    def test_invalid_stx(self):
        """Invalid STX should raise FramingError."""
        data = bytes.fromhex("AABB01010000000000598B")  # Wrong STX
        with pytest.raises(FramingError):
            Frame.from_bytes(data)

    def test_truncated_data(self):
        """Truncated data should raise FramingError."""
        # Header says 5 bytes of data, but we only provide 2
        data = bytes.fromhex("556601050000000001AABB")  # Only 2 data bytes
        with pytest.raises(FramingError):
            Frame.from_bytes(data)

    def test_invalid_crc(self):
        """Invalid CRC should raise CRCError."""
        # Valid frame but with wrong CRC
        data = bytes.fromhex("556601010000000000FFFF")  # Wrong CRC (should be 598B)
        with pytest.raises(CRCError) as exc_info:
            Frame.from_bytes(data)
        # Verify error has correct fields
        assert exc_info.value.expected == 0xFFFF
        assert exc_info.value.actual == 0x8B59

    def test_swapped_crc_bytes(self):
        """Swapped CRC bytes should raise CRCError."""
        # Correct CRC is 59 8B (little-endian), swapped is 8B 59
        data = bytes.fromhex("5566010100000000008B59")
        with pytest.raises(CRCError):
            Frame.from_bytes(data)


class TestFrameBuild:
    """Test Frame.build() factory method."""

    def test_default_ctrl(self):
        """Default (need_ack=False) should set CTRL=0 (fire-and-forget)."""
        frame = Frame.build(cmd_id=0x00, data=b"", seq=0)
        assert frame.ctrl == 0

    def test_need_ack_false(self):
        """need_ack=False should set CTRL=0 (no response expected)."""
        frame = Frame.build(cmd_id=0x00, data=b"", seq=0, need_ack=False)
        assert frame.ctrl == 0

    def test_need_ack_true(self):
        """need_ack=True should set CTRL=CTRL_NEED_ACK (0x01)."""
        frame = Frame.build(cmd_id=0x00, data=b"", seq=0, need_ack=True)
        assert frame.ctrl == CTRL_NEED_ACK

    def test_preserves_cmd_id(self):
        """build should preserve cmd_id."""
        frame = Frame.build(cmd_id=0x42, data=b"", seq=0)
        assert frame.cmd_id == 0x42

    def test_preserves_data(self):
        """build should preserve data."""
        frame = Frame.build(cmd_id=0x00, data=b"test", seq=0)
        assert frame.data == b"test"

    def test_preserves_seq(self):
        """build should preserve sequence number."""
        frame = Frame.build(cmd_id=0x00, data=b"", seq=0x1234)
        assert frame.seq == 0x1234


class TestFrameChapter4Examples:
    """Test Frame encoding/decoding with all Chapter 4 examples."""

    @pytest.mark.parametrize(
        "name,wire_hex,ctrl,seq,cmd_id,data_hex",
        [
            ("heartbeat", "556601010000000000598B", 1, 0, 0x00, "00"),
            ("zoom +1", "5566010100000005018d64", 1, 0, 0x05, "01"),
            ("zoom -1", "556601010000000 5FF5c6a", 1, 0, 0x05, "FF"),
            ("take photo", "556601010000000c0034ce", 1, 0, 0x0C, "00"),
            ("start recording", "556601010000000c0276ee", 1, 0, 0x0C, "02"),
            ("pan/tilt 100,100", "556601020000000764643dcf", 1, 0, 0x07, "6464"),
            ("one-key centering", "556601010000000801d112", 1, 0, 0x08, "01"),
            ("lock mode", "556601010000000c0357fe", 1, 0, 0x0C, "03"),
            ("follow mode", "556601010000000c04b08e", 1, 0, 0x0C, "04"),
            ("FPV mode", "556601010000000c05919e", 1, 0, 0x0C, "05"),
        ],
    )
    def test_chapter4_roundtrip(self, name, wire_hex, ctrl, seq, cmd_id, data_hex):
        """Verify Chapter 4 examples round-trip correctly."""
        # Clean up hex strings
        wire_hex = wire_hex.replace(" ", "")
        data_hex = data_hex.replace(" ", "")

        wire = bytes.fromhex(wire_hex)
        data = bytes.fromhex(data_hex)

        # Test from_bytes
        frame = Frame.from_bytes(wire)
        assert frame.ctrl == ctrl, f"{name}: ctrl mismatch"
        assert frame.seq == seq, f"{name}: seq mismatch"
        assert frame.cmd_id == cmd_id, f"{name}: cmd_id mismatch"
        assert frame.data == data, f"{name}: data mismatch"

        # Test to_bytes
        rebuilt = Frame(ctrl=ctrl, seq=seq, cmd_id=cmd_id, data=data)
        assert rebuilt.to_bytes() == wire, f"{name}: to_bytes mismatch"


class TestFrameEmptyPayload:
    """Test frames with empty payload."""

    def test_firmware_request(self):
        """Firmware version request has empty payload."""
        wire = bytes.fromhex("556601000000000164c4")
        frame = Frame.from_bytes(wire)
        assert frame.data == b""
        assert frame.data_len == 0

    def test_hardware_id_request(self):
        """Hardware ID request has empty payload."""
        wire = bytes.fromhex("556601000000000207f4")
        frame = Frame.from_bytes(wire)
        assert frame.data == b""
        assert frame.data_len == 0

    def test_empty_roundtrip(self):
        """Empty payload frame should round-trip."""
        original = Frame(ctrl=0, seq=0, cmd_id=0x01, data=b"")
        wire = original.to_bytes()
        restored = Frame.from_bytes(wire)
        assert restored.data == b""
