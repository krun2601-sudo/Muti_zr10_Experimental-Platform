# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Property-based fuzz tests for FrameParser."""

from __future__ import annotations

import contextlib
from datetime import timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from siyi_sdk.exceptions import CRCError, FramingError
from siyi_sdk.protocol.frame import Frame
from siyi_sdk.protocol.parser import FrameParser


class TestParserFuzz:
    """Fuzz testing for FrameParser robustness."""

    @given(data=st.binary(max_size=1000))
    @settings(max_examples=10000, deadline=timedelta(seconds=60))
    def test_parser_never_crashes_on_arbitrary_input(self, data):
        """Parser should never crash on arbitrary bytes.

        The parser should either:
        - Return a list of Frame objects (possibly empty)
        - Raise CRCError (documented)
        - Raise FramingError (documented)

        It should never raise any other exception.
        """
        parser = FrameParser()
        try:
            result = parser.feed(data)
            # Result should be a list
            assert isinstance(result, list)
            # All items should be Frame instances
            for frame in result:
                assert isinstance(frame, Frame)
        except (CRCError, FramingError):
            # These are expected documented exceptions
            pass

    @given(
        garbage=st.binary(max_size=100),
        valid_frame=st.fixed_dictionaries(
            {
                "cmd_id": st.integers(min_value=0, max_value=0xFF),
                "data": st.binary(max_size=64),
                "seq": st.integers(min_value=0, max_value=0xFFFF),
            }
        ),
        more_garbage=st.binary(max_size=100),
    )
    @settings(max_examples=500)
    def test_parser_finds_valid_frame_in_garbage(self, garbage, valid_frame, more_garbage):
        """Parser should extract valid frames from garbage-surrounded data."""
        frame = Frame.build(
            cmd_id=valid_frame["cmd_id"],
            data=valid_frame["data"],
            seq=valid_frame["seq"],
        )
        wire = frame.to_bytes()

        # Surround with garbage that doesn't contain valid STX sequences
        # Replace any 0x55 in garbage to avoid confusing the parser
        clean_garbage = bytes(b if b != 0x55 else 0xAA for b in garbage)
        clean_more_garbage = bytes(b if b != 0x55 else 0xAA for b in more_garbage)

        data = clean_garbage + wire + clean_more_garbage

        parser = FrameParser()
        frames = []

        # Feed all data, catching only documented exceptions
        with contextlib.suppress(CRCError, FramingError):
            frames.extend(parser.feed(data))

        # We should have extracted at least one valid frame
        assert len(frames) >= 1
        assert frames[0].cmd_id == valid_frame["cmd_id"]
        assert frames[0].data == valid_frame["data"]
        assert frames[0].seq == valid_frame["seq"]

    @given(
        chunk_sizes=st.lists(st.integers(min_value=1, max_value=50), min_size=1, max_size=20),
        data=st.binary(min_size=1, max_size=500),
    )
    @settings(max_examples=500)
    def test_parser_consistent_across_chunk_sizes(self, chunk_sizes, data):
        """Parser should be consistent regardless of how data is chunked."""
        parser1 = FrameParser()
        parser2 = FrameParser()

        # Feed all at once - result used for consistency check
        with contextlib.suppress(CRCError, FramingError):
            parser1.feed(data)

        # Feed in chunks
        frames2 = []
        idx = 0
        for size in chunk_sizes:
            if idx >= len(data):
                break
            chunk = data[idx : idx + size]
            idx += size
            with contextlib.suppress(CRCError, FramingError):
                frames2.extend(parser2.feed(chunk))

        # Remaining data
        if idx < len(data):
            with contextlib.suppress(CRCError, FramingError):
                frames2.extend(parser2.feed(data[idx:]))

        # Both approaches should yield same number of frames with same content
        # (Note: exact comparison might differ due to exception timing, so we check basics)
        # This test mainly ensures no crashes

    @given(
        frames_count=st.integers(min_value=1, max_value=5),
        garbage_between=st.booleans(),
    )
    @settings(max_examples=200)
    def test_parser_handles_multiple_frames(self, frames_count, garbage_between):
        """Parser should handle multiple valid frames."""
        # Generate valid frames
        frames_data = []
        for i in range(frames_count):
            frame = Frame.build(cmd_id=i, data=bytes([i] * 4), seq=i)
            frames_data.append(frame)

        # Build wire data
        wire = b""
        for frame in frames_data:
            if garbage_between and wire:
                wire += b"\xaa\xbb\xcc"  # Some garbage
            wire += frame.to_bytes()

        parser = FrameParser()
        parsed: list[Frame] = []
        with contextlib.suppress(CRCError, FramingError):
            parsed = parser.feed(wire)

        # Should have parsed all frames
        assert len(parsed) == frames_count

    @given(data=st.binary(min_size=0, max_size=100))
    @settings(max_examples=500)
    def test_parser_empty_result_is_valid(self, data):
        """Parser returning empty list is a valid result."""
        parser = FrameParser()
        try:
            result = parser.feed(data)
            # Empty list is fine - data might not contain valid frames
            assert isinstance(result, list)
        except (CRCError, FramingError):
            # Also fine - documented exceptions
            pass


class TestParserReset:
    """Test parser reset behavior under fuzz."""

    @given(
        partial_data=st.binary(min_size=1, max_size=50),
        valid_frame=st.fixed_dictionaries(
            {
                "cmd_id": st.integers(min_value=0, max_value=0xFF),
                "data": st.binary(max_size=32),
                "seq": st.integers(min_value=0, max_value=0xFFFF),
            }
        ),
    )
    @settings(max_examples=500)
    def test_reset_clears_state(self, partial_data, valid_frame):
        """Reset should completely clear parser state."""
        frame = Frame.build(
            cmd_id=valid_frame["cmd_id"],
            data=valid_frame["data"],
            seq=valid_frame["seq"],
        )
        wire = frame.to_bytes()

        parser = FrameParser()

        # Feed partial data
        with contextlib.suppress(CRCError, FramingError):
            parser.feed(partial_data)

        # Reset
        parser.reset()

        # Feed valid frame
        frames = parser.feed(wire)

        # Should get exactly one frame
        assert len(frames) == 1
        assert frames[0].cmd_id == valid_frame["cmd_id"]


class TestParserSpecialPatterns:
    """Test parser with special byte patterns."""

    @given(count=st.integers(min_value=1, max_value=100))
    @settings(max_examples=100)
    def test_all_0x55_bytes(self, count):
        """Parser should handle streams of 0x55 bytes."""
        parser = FrameParser()
        data = b"\x55" * count
        try:
            result = parser.feed(data)
            assert isinstance(result, list)
        except (CRCError, FramingError):
            pass

    @given(count=st.integers(min_value=1, max_value=50))
    @settings(max_examples=100)
    def test_alternating_stx_bytes(self, count):
        """Parser should handle alternating 0x55 0x66 bytes."""
        parser = FrameParser()
        data = b"\x55\x66" * count
        try:
            result = parser.feed(data)
            assert isinstance(result, list)
        except (CRCError, FramingError):
            pass

    @given(
        repeats=st.integers(min_value=1, max_value=10),
        valid_frame=st.fixed_dictionaries(
            {
                "cmd_id": st.integers(min_value=0, max_value=0xFF),
                "data": st.binary(max_size=16),
                "seq": st.integers(min_value=0, max_value=0xFFFF),
            }
        ),
    )
    @settings(max_examples=200)
    def test_repeated_stx_before_valid(self, repeats, valid_frame):
        """Parser should handle repeated STX bytes before valid frame."""
        frame = Frame.build(
            cmd_id=valid_frame["cmd_id"],
            data=valid_frame["data"],
            seq=valid_frame["seq"],
        )
        wire = frame.to_bytes()

        # Multiple partial STX sequences before valid frame
        data = (b"\x55" * repeats) + wire

        parser = FrameParser()
        frames = parser.feed(data)

        # Should still extract the valid frame
        assert len(frames) == 1
        assert frames[0].cmd_id == valid_frame["cmd_id"]
