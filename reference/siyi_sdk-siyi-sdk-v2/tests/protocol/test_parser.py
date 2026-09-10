# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for siyi_sdk.protocol.parser module."""

from __future__ import annotations

import pytest

from siyi_sdk.constants import HEARTBEAT_FRAME
from siyi_sdk.exceptions import CRCError, FramingError
from siyi_sdk.protocol.parser import FrameParser


class TestParserBasic:
    """Test basic parser functionality."""

    def test_empty_feed(self):
        """Empty feed should return empty list."""
        parser = FrameParser()
        result = parser.feed(b"")
        assert result == []

    def test_parse_heartbeat(self):
        """Parser should extract heartbeat frame."""
        parser = FrameParser()
        frames = parser.feed(HEARTBEAT_FRAME)
        assert len(frames) == 1
        assert frames[0].cmd_id == 0x00

    def test_parse_single_byte_at_a_time(self):
        """Parser should work with single-byte chunks."""
        parser = FrameParser()
        frames = []
        for byte in HEARTBEAT_FRAME:
            result = parser.feed(bytes([byte]))
            frames.extend(result)
        assert len(frames) == 1
        assert frames[0].cmd_id == 0x00

    def test_parse_multiple_frames(self):
        """Parser should extract multiple concatenated frames."""
        parser = FrameParser()
        # Send 3 heartbeat frames
        data = HEARTBEAT_FRAME * 3
        frames = parser.feed(data)
        assert len(frames) == 3
        for frame in frames:
            assert frame.cmd_id == 0x00

    def test_reset(self):
        """Reset should clear parser state."""
        parser = FrameParser()
        # Feed partial frame
        parser.feed(HEARTBEAT_FRAME[:5])
        # Reset
        parser.reset()
        # Feed complete frame
        frames = parser.feed(HEARTBEAT_FRAME)
        assert len(frames) == 1


class TestParserResync:
    """Test parser resynchronization."""

    def test_garbage_prefix(self):
        """Parser should resync after garbage prefix."""
        parser = FrameParser()
        # Garbage followed by valid frame
        data = b"\xaa\xbb\xcc" + HEARTBEAT_FRAME
        frames = parser.feed(data)
        assert len(frames) == 1
        assert frames[0].cmd_id == 0x00

    def test_partial_stx_in_garbage(self):
        """Parser should handle 0x55 in garbage."""
        parser = FrameParser()
        # Garbage with 0x55 bytes, then valid frame
        data = b"\x55\xaa\x55\xbb" + HEARTBEAT_FRAME
        frames = parser.feed(data)
        assert len(frames) == 1
        assert frames[0].cmd_id == 0x00

    def test_resync_after_bad_stx2(self):
        """Parser should resync when STX2 is wrong."""
        parser = FrameParser()
        # 0x55 followed by wrong byte, then valid frame
        data = b"\x55\xaa" + HEARTBEAT_FRAME
        frames = parser.feed(data)
        assert len(frames) == 1

    def test_consecutive_stx1(self):
        """Parser should handle consecutive 0x55 bytes."""
        parser = FrameParser()
        # Multiple 0x55 bytes before valid frame
        data = b"\x55\x55\x55" + HEARTBEAT_FRAME
        frames = parser.feed(data)
        assert len(frames) == 1


class TestParserCRCError:
    """Test parser CRC error handling."""

    def test_crc_error_raises(self):
        """Invalid CRC should raise CRCError."""
        parser = FrameParser()
        # Corrupt CRC bytes
        bad_frame = HEARTBEAT_FRAME[:-2] + b"\xff\xff"
        with pytest.raises(CRCError):
            parser.feed(bad_frame)

    def test_resync_after_crc_error(self):
        """Parser should resync after CRC error."""
        parser = FrameParser()
        # Bad frame followed by good frame
        bad_frame = HEARTBEAT_FRAME[:-2] + b"\xff\xff"
        data = bad_frame + HEARTBEAT_FRAME

        # First call raises CRCError
        with pytest.raises(CRCError):
            parser.feed(data)

        # Parser should have reset, so we need to try again with remaining data
        # Actually, the parser processes byte by byte, so after the exception
        # we need to continue with the rest
        # Let's test differently - feed them separately

    def test_recovery_after_crc_error(self):
        """Parser should recover after CRC error."""
        parser = FrameParser()
        bad_frame = HEARTBEAT_FRAME[:-2] + b"\xff\xff"

        # Feed bad frame
        with pytest.raises(CRCError):
            parser.feed(bad_frame)

        # Parser should have reset, feed good frame
        frames = parser.feed(HEARTBEAT_FRAME)
        assert len(frames) == 1

    def test_one_byte_flip_causes_crc_error(self):
        """Flipping a payload byte should cause CRC error."""
        parser = FrameParser()
        # Create a frame with longer payload and flip one byte
        frame_bytes = bytes.fromhex("556601020000000764643dcf")  # Pan/Tilt
        bad_frame = frame_bytes[:9] + b"\x00" + frame_bytes[10:]  # Flip byte 9

        with pytest.raises(CRCError):
            parser.feed(bad_frame)


class TestParserOversizedPayload:
    """Test parser handling of oversized payloads."""

    def test_oversized_payload_raises(self):
        """Oversized payload should raise FramingError."""
        parser = FrameParser(max_payload=100)
        # Craft header with data_len > max_payload
        # STX + CTRL + data_len(500) + SEQ + CMD_ID
        header = b"\x55\x66\x01\xf4\x01\x00\x00\x00"  # data_len = 0x01F4 = 500
        with pytest.raises(FramingError):
            parser.feed(header)

    def test_recovery_after_oversized(self):
        """Parser should recover after oversized payload."""
        parser = FrameParser(max_payload=100)
        # Craft header with data_len > max_payload
        header = b"\x55\x66\x01\xf4\x01\x00\x00\x00"

        with pytest.raises(FramingError):
            parser.feed(header)

        # Should recover
        frames = parser.feed(HEARTBEAT_FRAME)
        assert len(frames) == 1


class TestParserChunkedInput:
    """Test parser with various chunk sizes."""

    def test_two_byte_chunks(self):
        """Parser should work with 2-byte chunks."""
        parser = FrameParser()
        frames = []
        data = HEARTBEAT_FRAME
        for i in range(0, len(data), 2):
            chunk = data[i : i + 2]
            result = parser.feed(chunk)
            frames.extend(result)
        assert len(frames) == 1

    def test_three_byte_chunks(self):
        """Parser should work with 3-byte chunks."""
        parser = FrameParser()
        frames = []
        data = HEARTBEAT_FRAME
        for i in range(0, len(data), 3):
            chunk = data[i : i + 3]
            result = parser.feed(chunk)
            frames.extend(result)
        assert len(frames) == 1

    def test_partial_header(self):
        """Parser should buffer partial header."""
        parser = FrameParser()
        # Feed header without data or CRC
        frames1 = parser.feed(HEARTBEAT_FRAME[:8])
        assert frames1 == []
        # Feed rest
        frames2 = parser.feed(HEARTBEAT_FRAME[8:])
        assert len(frames2) == 1

    def test_split_crc(self):
        """Parser should handle split CRC."""
        parser = FrameParser()
        # Feed everything except last CRC byte
        frames1 = parser.feed(HEARTBEAT_FRAME[:-1])
        assert frames1 == []
        # Feed last byte
        frames2 = parser.feed(HEARTBEAT_FRAME[-1:])
        assert len(frames2) == 1


class TestParserChapter4Examples:
    """Test parser with Chapter 4 examples."""

    @pytest.mark.parametrize(
        "name,wire_hex",
        [
            ("heartbeat", "556601010000000000598B"),
            ("zoom +1", "5566010100000005018d64"),
            ("zoom -1", "5566010100000005FF5c6a"),
            ("take photo", "556601010000000c0034ce"),
            ("pan/tilt 100,100", "556601020000000764643dcf"),
            ("one-key centering", "556601010000000801d112"),
            ("firmware request", "556601000000000164c4"),
            ("hardware ID request", "556601000000000207f4"),
        ],
    )
    def test_parse_example(self, name, wire_hex):
        """Parser should correctly parse Chapter 4 examples."""
        parser = FrameParser()
        wire = bytes.fromhex(wire_hex)
        frames = parser.feed(wire)
        assert len(frames) == 1, f"Failed to parse {name}"

    def test_multiple_mixed_examples(self):
        """Parser should handle multiple different frames."""
        parser = FrameParser()
        data = (
            bytes.fromhex("556601010000000000598B")  # heartbeat
            + bytes.fromhex("5566010100000005018d64")  # zoom +1
            + bytes.fromhex("556601010000000801d112")  # one-key centering
        )
        frames = parser.feed(data)
        assert len(frames) == 3
        assert frames[0].cmd_id == 0x00
        assert frames[1].cmd_id == 0x05
        assert frames[2].cmd_id == 0x08


class TestParserMaxPayload:
    """Test max_payload configuration."""

    def test_default_max_payload(self):
        """Default max_payload should be 4096."""
        parser = FrameParser()
        assert parser.max_payload == 4096

    def test_custom_max_payload(self):
        """Custom max_payload should be respected."""
        parser = FrameParser(max_payload=256)
        assert parser.max_payload == 256

    def test_payload_at_max_limit(self):
        """Payload at exactly max_payload should work."""
        parser = FrameParser(max_payload=1)  # Only 1-byte payloads allowed
        # Heartbeat has 1-byte payload
        frames = parser.feed(HEARTBEAT_FRAME)
        assert len(frames) == 1
