# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for siyi_sdk.protocol.crc module."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from siyi_sdk.constants import CRC16_POLY, CRC16_TABLE
from siyi_sdk.protocol.crc import crc16, crc16_check


class TestCRC16Vectors:
    """Test CRC16 with known test vectors from SIYI SDK Protocol."""

    @pytest.mark.parametrize(
        "description,input_hex,expected_crc,wire_bytes",
        [
            # Vector 1: Request firmware version
            ("Request fw version", "5566010000000001", 0xC464, "64C4"),
            # Vector 2: Request hardware ID
            ("Request hardware ID", "5566010000000002", 0xF407, "07F4"),
            # Vector 3: Manual zoom +1
            ("Manual zoom +1", "556601010000000501", 0x648D, "8D64"),
            # Vector 4: Take photo (CMD_ID=0x0C, DATA=0x00)
            ("Take photo", "55660101000000 0C00", 0xCE34, "34CE"),
            # Vector 5: TCP heartbeat
            ("TCP heartbeat", "556601010000000000", 0x8B59, "598B"),
            # Vector 6: Pan/Tilt 100,100
            ("Pan/Tilt 100,100", "556601020000000764 64", 0xCF3D, "3DCF"),
            # Vector 7: One-key centering
            ("One-key centering", "5566010100000008 01", 0x12D1, "D112"),
        ],
    )
    def test_crc16_vector(self, description, input_hex, expected_crc, wire_bytes):
        """Test CRC16 calculation against known vectors."""
        # Remove spaces from input
        input_hex = input_hex.replace(" ", "")
        input_bytes = bytes.fromhex(input_hex)
        actual_crc = crc16(input_bytes)
        msg = f"{description}: expected 0x{expected_crc:04X}, got 0x{actual_crc:04X}"
        assert actual_crc == expected_crc, msg

    def test_crc16_empty_input(self):
        """CRC16 of empty input should be 0x0000."""
        assert crc16(b"") == 0x0000

    def test_crc16_with_init(self):
        """CRC16 should accept custom initial value."""
        # With init=0, result should be same as default
        assert crc16(b"test", init=0) == crc16(b"test")
        # With different init, result should differ
        assert crc16(b"test", init=0x1234) != crc16(b"test")


class TestCRC16Check:
    """Test CRC16 verification function."""

    def test_heartbeat_frame(self):
        """Verify heartbeat frame CRC."""
        frame = bytes.fromhex("556601010000000000")
        crc = bytes.fromhex("598B")
        assert crc16_check(frame, crc) is True

    def test_invalid_crc(self):
        """Invalid CRC should return False."""
        frame = bytes.fromhex("556601010000000000")
        crc = bytes.fromhex("0000")  # Wrong CRC
        assert crc16_check(frame, crc) is False

    def test_swapped_crc_bytes(self):
        """Swapped CRC bytes should fail."""
        frame = bytes.fromhex("556601010000000000")
        # Correct is 59 8B, swapped would be 8B 59
        crc = bytes.fromhex("8B59")  # Swapped (big-endian instead of little)
        assert crc16_check(frame, crc) is False


class TestCRC16TableValidation:
    """Validate CRC16 table from SIYI spec."""

    def test_table_entry_zero(self):
        """Table entry for 0 should be 0."""
        assert CRC16_TABLE[0] == 0x0000

    def test_table_entry_one(self):
        """Table entry for 1 should be polynomial."""
        # For CRC-16/XMODEM, T[1] = poly = 0x1021
        assert CRC16_TABLE[1] == CRC16_POLY

    def test_table_consistency_with_crc16(self):
        """Verify table entries match crc16() for single bytes.

        The SIYI CRC algorithm is: T[i] = crc16(bytes([i])) with init=0.
        This verifies the table and crc16 implementation are consistent.
        """
        for i in range(256):
            # For single byte b with init=0:
            # temp = (0 >> 8) & 0xFF = 0
            # crc = (0 << 8) ^ T[b ^ 0] = T[b]
            result = crc16(bytes([i]))
            assert result == CRC16_TABLE[i], f"Table[{i}] mismatch: {result} != {CRC16_TABLE[i]}"

    @given(st.binary(min_size=0, max_size=100))
    @settings(max_examples=100)
    def test_crc16_is_deterministic(self, data):
        """CRC16 should be deterministic (same input = same output)."""
        result1 = crc16(data)
        result2 = crc16(data)
        assert result1 == result2


class TestCRC16EdgeCases:
    """Test edge cases for CRC16."""

    def test_single_byte(self):
        """CRC of single byte should match table lookup."""
        for i in range(256):
            result = crc16(bytes([i]))
            # For XMODEM, CRC of single byte b is:
            # crc = 0, temp = 0, table[b^0] = table[b]
            # crc = (0 << 8) ^ table[b] = table[b]
            expected = CRC16_TABLE[i]
            assert result == expected

    def test_all_zeros(self):
        """CRC of all zeros."""
        data = b"\x00" * 10
        result = crc16(data)
        # Verify consistency
        assert result == crc16(data)

    def test_all_ones(self):
        """CRC of all 0xFF bytes."""
        data = b"\xff" * 10
        result = crc16(data)
        # Verify consistency
        assert result == crc16(data)

    def test_incrementing_bytes(self):
        """CRC of incrementing byte sequence."""
        data = bytes(range(256))
        result = crc16(data)
        # Verify consistency
        assert result == crc16(data)


class TestCRC16ChapterExamples:
    """Test CRC16 with Chapter 4 communication examples."""

    @pytest.mark.parametrize(
        "name,full_frame_hex",
        [
            ("zoom +1", "55 66 01 01 00 00 00 05 01 8d 64"),
            ("zoom -1", "55 66 01 01 00 00 00 05 FF 5c 6a"),
            ("absolute zoom 4.5x", "55 66 01 02 00 01 00 0F 04 05 c0 bb"),
            ("focus +1", "55 66 01 01 00 00 00 06 01 de 31"),
            ("take photo", "55 66 01 01 00 00 00 0c 00 34 ce"),
            ("start video recording", "55 66 01 01 00 00 00 0c 02 76 ee"),
            ("pan/tilt 100,100", "55 66 01 02 00 00 00 07 64 64 3d cf"),
            ("one-key centering", "55 66 01 01 00 00 00 08 01 d1 12"),
            ("gimbal status info", "55 66 01 00 00 00 00 0a 0f 75"),
            ("retrieve hardware ID", "55 66 01 00 00 00 00 02 07 f4"),
            ("retrieve firmware version", "55 66 01 00 00 00 00 01 64 c4"),
            ("lock mode", "55 66 01 01 00 00 00 0c 03 57 fe"),
            ("follow mode", "55 66 01 01 00 00 00 0c 04 b0 8e"),
            ("FPV mode", "55 66 01 01 00 00 00 0c 05 91 9e"),
            ("retrieve attitude data", "55 66 01 00 00 00 00 0d e8 05"),
        ],
    )
    def test_chapter4_example(self, name, full_frame_hex):
        """Verify CRC in Chapter 4 example frames."""
        # Remove spaces
        full_frame_hex = full_frame_hex.replace(" ", "")
        full_frame = bytes.fromhex(full_frame_hex)

        # Frame without CRC (last 2 bytes)
        frame_without_crc = full_frame[:-2]
        crc_bytes = full_frame[-2:]

        # Verify CRC
        expected_crc = int.from_bytes(crc_bytes, "little")
        actual_crc = crc16(frame_without_crc)
        msg = f"{name}: expected 0x{expected_crc:04X}, got 0x{actual_crc:04X}"
        assert actual_crc == expected_crc, msg

        # Also verify with crc16_check
        assert crc16_check(frame_without_crc, crc_bytes) is True
