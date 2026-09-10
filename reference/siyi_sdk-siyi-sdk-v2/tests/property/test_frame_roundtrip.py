# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Property-based tests for Frame roundtrip."""

from __future__ import annotations

from datetime import timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from siyi_sdk.protocol.frame import Frame
from siyi_sdk.protocol.parser import FrameParser


class TestFrameRoundtrip:
    """Property-based tests for Frame serialization/deserialization."""

    @given(
        cmd_id=st.integers(min_value=0, max_value=0xFF),
        data=st.binary(max_size=256),
        seq=st.integers(min_value=0, max_value=0xFFFF),
        need_ack=st.booleans(),
    )
    @settings(max_examples=10000, deadline=timedelta(seconds=60))
    def test_frame_roundtrip_via_from_bytes(self, cmd_id, data, seq, need_ack):
        """Frame should survive to_bytes/from_bytes roundtrip."""
        original = Frame.build(cmd_id=cmd_id, data=data, seq=seq, need_ack=need_ack)
        wire = original.to_bytes()
        restored = Frame.from_bytes(wire)

        assert restored.ctrl == original.ctrl
        assert restored.seq == original.seq
        assert restored.cmd_id == original.cmd_id
        assert restored.data == original.data

    @given(
        cmd_id=st.integers(min_value=0, max_value=0xFF),
        data=st.binary(max_size=256),
        seq=st.integers(min_value=0, max_value=0xFFFF),
        need_ack=st.booleans(),
    )
    @settings(max_examples=10000, deadline=timedelta(seconds=60))
    def test_frame_roundtrip_via_parser(self, cmd_id, data, seq, need_ack):
        """Frame should survive to_bytes/parser.feed roundtrip."""
        original = Frame.build(cmd_id=cmd_id, data=data, seq=seq, need_ack=need_ack)
        wire = original.to_bytes()

        parser = FrameParser()
        frames = parser.feed(wire)

        assert len(frames) == 1
        restored = frames[0]

        assert restored.ctrl == original.ctrl
        assert restored.seq == original.seq
        assert restored.cmd_id == original.cmd_id
        assert restored.data == original.data

    @given(
        frames=st.lists(
            st.fixed_dictionaries(
                {
                    "cmd_id": st.integers(min_value=0, max_value=0xFF),
                    "data": st.binary(max_size=64),
                    "seq": st.integers(min_value=0, max_value=0xFFFF),
                }
            ),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=200)
    def test_multiple_frames_roundtrip(self, frames):
        """Multiple frames concatenated should all parse correctly."""
        # Build frames
        originals = [Frame.build(cmd_id=f["cmd_id"], data=f["data"], seq=f["seq"]) for f in frames]

        # Concatenate wire format
        wire = b"".join(f.to_bytes() for f in originals)

        # Parse
        parser = FrameParser()
        parsed = parser.feed(wire)

        assert len(parsed) == len(originals)
        for orig, restored in zip(originals, parsed, strict=True):
            assert restored.ctrl == orig.ctrl
            assert restored.seq == orig.seq
            assert restored.cmd_id == orig.cmd_id
            assert restored.data == orig.data

    @given(
        cmd_id=st.integers(min_value=0, max_value=0xFF),
        data=st.binary(max_size=256),
        seq=st.integers(min_value=0, max_value=0xFFFF),
        chunk_size=st.integers(min_value=1, max_value=20),
    )
    @settings(max_examples=500)
    def test_chunked_roundtrip(self, cmd_id, data, seq, chunk_size):
        """Frame should parse correctly regardless of chunk size."""
        original = Frame.build(cmd_id=cmd_id, data=data, seq=seq)
        wire = original.to_bytes()

        parser = FrameParser()
        frames = []

        # Feed in chunks
        for i in range(0, len(wire), chunk_size):
            chunk = wire[i : i + chunk_size]
            frames.extend(parser.feed(chunk))

        assert len(frames) == 1
        restored = frames[0]

        assert restored.ctrl == original.ctrl
        assert restored.seq == original.seq
        assert restored.cmd_id == original.cmd_id
        assert restored.data == original.data


class TestFrameDataLenConsistency:
    """Test data_len property consistency."""

    @given(data=st.binary(max_size=1000))
    @settings(max_examples=500)
    def test_data_len_matches_data(self, data):
        """data_len property should always match len(data)."""
        frame = Frame(ctrl=1, seq=0, cmd_id=0, data=data)
        assert frame.data_len == len(data)

    @given(
        cmd_id=st.integers(min_value=0, max_value=0xFF),
        data=st.binary(max_size=256),
        seq=st.integers(min_value=0, max_value=0xFFFF),
    )
    @settings(max_examples=500)
    def test_wire_format_data_len_correct(self, cmd_id, data, seq):
        """Wire format should have correct data_len field."""
        frame = Frame.build(cmd_id=cmd_id, data=data, seq=seq)
        wire = frame.to_bytes()

        # data_len is at offset 3-4 (little-endian uint16)
        wire_data_len = int.from_bytes(wire[3:5], "little")
        assert wire_data_len == len(data)
