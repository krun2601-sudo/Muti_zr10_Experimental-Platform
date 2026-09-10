# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Frame encoding and decoding for SIYI protocol.

This module provides the Frame dataclass for representing SIYI protocol
frames and methods for serialization/deserialization.

Frame Structure (from SIYI SDK Protocol):
    Offset  Bytes  Field     Description
    0       2      STX       Start marker (0x6655, wire: 0x55 0x66)
    2       1      CTRL      Control byte (bit0=need_ack, bit1=ack_pack)
    3       2      Data_len  Payload length (little-endian)
    5       2      SEQ       Sequence number (little-endian)
    7       1      CMD_ID    Command ID
    8       N      DATA      Payload (N = Data_len)
    8+N     2      CRC16     CRC-16/XMODEM (little-endian)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..constants import (
    CRC_LEN,
    CTRL_NEED_ACK,
    HEADER_LEN,
    MIN_FRAME_LEN,
    STX,
    STX_BYTES,
)
from ..exceptions import CRCError, FramingError
from .crc import crc16


@dataclass(frozen=True, slots=True)
class Frame:
    """SIYI protocol frame.

    Attributes:
        ctrl: Control byte (bit0=need_ack, bit1=ack_pack).
        seq: Sequence number (0-65535).
        cmd_id: Command ID.
        data: Payload bytes.

    """

    ctrl: int
    seq: int
    cmd_id: int
    data: bytes

    @property
    def data_len(self) -> int:
        """Get the payload length.

        Returns:
            Length of the data payload in bytes.

        """
        return len(self.data)

    def to_bytes(self) -> bytes:
        """Serialize frame to wire format.

        Returns:
            Complete frame bytes including STX, header, payload, and CRC.

        Example:
            >>> frame = Frame(ctrl=1, seq=0, cmd_id=0x00, data=b"")
            >>> frame.to_bytes().hex()
            '556601010000000000598b'

        """
        # Pack header: STX (LE u16) + CTRL (u8) + data_len (LE u16) + SEQ (LE u16) + CMD_ID (u8)
        header = struct.pack(
            "<HBHHB",
            STX,
            self.ctrl,
            self.data_len,
            self.seq,
            self.cmd_id,
        )
        # Frame without CRC
        frame_without_crc = header + self.data
        # Calculate CRC
        crc_value = crc16(frame_without_crc)
        # Append CRC in little-endian
        crc_bytes = struct.pack("<H", crc_value)
        return frame_without_crc + crc_bytes

    @classmethod
    def from_bytes(cls, buf: bytes) -> Frame:
        """Deserialize frame from wire format.

        Args:
            buf: Complete frame bytes including STX, header, payload, and CRC.

        Returns:
            Parsed Frame object.

        Raises:
            FramingError: If STX is invalid or frame is truncated.
            CRCError: If CRC checksum does not match.

        Example:
            >>> frame_bytes = bytes.fromhex("556601010000000000598b")
            >>> frame = Frame.from_bytes(frame_bytes)
            >>> frame.cmd_id
            0

        """
        # Check minimum length
        if len(buf) < MIN_FRAME_LEN:
            raise FramingError(f"Frame too short: {len(buf)} bytes, minimum is {MIN_FRAME_LEN}")

        # Check STX
        if buf[0:2] != STX_BYTES:
            raise FramingError(f"Invalid STX: expected 0x5566, got 0x{buf[0]:02X}{buf[1]:02X}")

        # Unpack header
        _stx, ctrl, data_len, seq, cmd_id = struct.unpack("<HBHHB", buf[:HEADER_LEN])

        # Check we have enough bytes for full frame
        expected_len = HEADER_LEN + data_len + CRC_LEN
        if len(buf) < expected_len:
            raise FramingError(f"Frame truncated: have {len(buf)} bytes, expected {expected_len}")

        # Extract payload and CRC
        data = buf[HEADER_LEN : HEADER_LEN + data_len]
        crc_bytes = buf[HEADER_LEN + data_len : HEADER_LEN + data_len + CRC_LEN]

        # Verify CRC
        frame_without_crc = buf[: HEADER_LEN + data_len]
        expected_crc = int.from_bytes(crc_bytes, "little")
        actual_crc = crc16(frame_without_crc)

        if expected_crc != actual_crc:
            frame_hex = buf[: HEADER_LEN + data_len + CRC_LEN].hex(sep=" ")
            raise CRCError(
                expected=expected_crc,
                actual=actual_crc,
                frame_hex=frame_hex,
            )

        return cls(ctrl=ctrl, seq=seq, cmd_id=cmd_id, data=data)

    @classmethod
    def build(
        cls,
        cmd_id: int,
        data: bytes,
        seq: int,
        *,
        need_ack: bool = False,
    ) -> Frame:
        """Build a frame for sending.

        Sets the CTRL byte per the SIYI protocol bit-field spec:
        - bit[0] (CTRL_NEED_ACK=0x01): set when sender needs a response
        - bit[1] (CTRL_ACK_PACK=0x02): set when this frame IS a response

        Client requests that expect a reply use need_ack=True (CTRL=0x01).
        Fire-and-forget commands use need_ack=False (CTRL=0x00).

        Args:
            cmd_id: Command ID.
            data: Payload bytes.
            seq: Sequence number.
            need_ack: If True, sets CTRL=CTRL_NEED_ACK (0x01, bit[0]), telling
                the camera to send a response. Default is False (fire-and-forget,
                CTRL=0).

        Returns:
            Constructed Frame object.

        Example:
            >>> # Build a firmware request frame (expects response)
            >>> frame = Frame.build(cmd_id=0x01, data=b"", seq=0, need_ack=True)
            >>> frame.ctrl
            1

        """
        ctrl = CTRL_NEED_ACK if need_ack else 0
        return cls(ctrl=ctrl, seq=seq, cmd_id=cmd_id, data=data)
