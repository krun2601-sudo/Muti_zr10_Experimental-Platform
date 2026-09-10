# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""CRC-16/XMODEM implementation for SIYI protocol.

This module provides CRC-16/XMODEM checksum calculation using the
lookup table defined in the SIYI SDK protocol specification.

Algorithm: CRC-16/XMODEM
- Polynomial: X^16 + X^12 + X^5 + 1 = 0x1021
- Initial value: 0x0000
- No reflect-in, no reflect-out, no final XOR
"""

from __future__ import annotations

from ..constants import CRC16_INIT, CRC16_TABLE


def crc16(buf: bytes, init: int = CRC16_INIT) -> int:
    """Calculate CRC-16/XMODEM checksum.

    Uses the table-driven algorithm from SIYI SDK Protocol Chapter 4.

    Args:
        buf: Input bytes to calculate CRC over.
        init: Initial CRC value (default: 0x0000).

    Returns:
        16-bit CRC value.

    Example:
        >>> crc16(b"")
        0
        >>> hex(crc16(bytes.fromhex("5566010000000001")))
        '0xc464'

    """
    crc = init
    for b in buf:
        temp = (crc >> 8) & 0xFF
        crc = ((crc << 8) & 0xFFFF) ^ CRC16_TABLE[b ^ temp]
    return crc


def crc16_check(frame_without_crc: bytes, crc_le: bytes) -> bool:
    """Verify CRC-16/XMODEM checksum.

    Computes the CRC of the frame data and compares against the
    provided CRC bytes (little-endian).

    Args:
        frame_without_crc: Frame bytes excluding the 2-byte CRC.
        crc_le: 2-byte CRC in little-endian format.

    Returns:
        True if the CRC matches, False otherwise.

    Example:
        >>> # Heartbeat frame: 55 66 01 01 00 00 00 00 00 59 8B
        >>> frame = bytes.fromhex("556601010000000000")
        >>> crc = bytes.fromhex("598B")
        >>> crc16_check(frame, crc)
        True

    """
    expected = int.from_bytes(crc_le, "little")
    actual = crc16(frame_without_crc)
    return expected == actual
