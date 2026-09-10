# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Streaming frame parser for SIYI protocol.

This module provides a state-machine based parser for extracting
complete frames from a byte stream. The parser handles:
- Partial frame buffering across multiple feed() calls
- Automatic resynchronization on corrupted data
- CRC validation with error reporting
"""

from __future__ import annotations

from enum import IntEnum, auto
from typing import TYPE_CHECKING

import structlog

from ..constants import CRC_LEN, STX_BYTES
from ..exceptions import CRCError, FramingError
from .crc import crc16
from .frame import Frame

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class _ParserState(IntEnum):
    """Internal parser state machine states."""

    AWAIT_STX1 = auto()
    AWAIT_STX2 = auto()
    READ_CTRL = auto()
    READ_DATA_LEN_LO = auto()
    READ_DATA_LEN_HI = auto()
    READ_SEQ_LO = auto()
    READ_SEQ_HI = auto()
    READ_CMD_ID = auto()
    READ_DATA = auto()
    READ_CRC_LO = auto()
    READ_CRC_HI = auto()
    VERIFY_CRC = auto()


class FrameParser:
    """Streaming SIYI protocol frame parser.

    This parser implements a state machine that processes bytes
    incrementally, allowing frames to be extracted from partial
    or concatenated data streams.

    The parser will:
    - Buffer partial frames across feed() calls
    - Resynchronize on invalid STX bytes (silently)
    - Raise CRCError on checksum failures (then resync)
    - Raise FramingError on oversized payloads (then resync)

    Attributes:
        max_payload: Maximum allowed payload size.

    Example:
        >>> parser = FrameParser()
        >>> frames = parser.feed(bytes.fromhex("556601010000000000598b"))
        >>> len(frames)
        1
        >>> frames[0].cmd_id
        0

    """

    def __init__(self, max_payload: int = 4096) -> None:
        """Initialize the frame parser.

        Args:
            max_payload: Maximum allowed payload size in bytes.
                Frames with larger payloads will trigger FramingError.

        """
        self.max_payload = max_payload
        self._state = _ParserState.AWAIT_STX1
        self._ctrl: int = 0
        self._data_len: int = 0
        self._seq: int = 0
        self._cmd_id: int = 0
        self._data: bytearray = bytearray()
        self._crc_lo: int = 0
        self._crc_hi: int = 0
        self._frame_buffer: bytearray = bytearray()

    def reset(self) -> None:
        """Reset parser state.

        Clears all buffered data and returns to initial state.
        Call this after a connection reset or protocol error.

        """
        self._state = _ParserState.AWAIT_STX1
        self._ctrl = 0
        self._data_len = 0
        self._seq = 0
        self._cmd_id = 0
        self._data = bytearray()
        self._crc_lo = 0
        self._crc_hi = 0
        self._frame_buffer = bytearray()

    def feed(self, chunk: bytes) -> list[Frame]:
        """Process incoming bytes and extract complete frames.

        This method processes the input bytes incrementally using a
        state machine. Complete frames are returned as a list.

        Args:
            chunk: New bytes to process.

        Returns:
            List of complete frames extracted from the stream.
            May be empty if no complete frames are available yet.

        Raises:
            CRCError: If a frame has an invalid CRC. The parser will
                resync after raising this exception.
            FramingError: If a frame has an oversized payload. The parser
                will resync after raising this exception.

        """
        frames: list[Frame] = []
        idx = 0

        while idx < len(chunk):
            byte = chunk[idx]
            idx += 1

            if self._state == _ParserState.AWAIT_STX1:
                if byte == STX_BYTES[0]:  # 0x55
                    self._frame_buffer = bytearray([byte])
                    self._state = _ParserState.AWAIT_STX2
                # else: silently discard, stay in AWAIT_STX1

            elif self._state == _ParserState.AWAIT_STX2:
                if byte == STX_BYTES[1]:  # 0x66
                    self._frame_buffer.append(byte)
                    self._state = _ParserState.READ_CTRL
                elif byte == STX_BYTES[0]:  # 0x55
                    # Could be start of new frame
                    self._frame_buffer = bytearray([byte])
                    # Stay in AWAIT_STX2
                else:
                    # Invalid, resync
                    logger.warning(
                        "Invalid STX byte, resyncing",
                        expected=f"0x{STX_BYTES[1]:02X}",
                        actual=f"0x{byte:02X}",
                    )
                    self._state = _ParserState.AWAIT_STX1
                    self._frame_buffer = bytearray()

            elif self._state == _ParserState.READ_CTRL:
                self._ctrl = byte
                self._frame_buffer.append(byte)
                self._state = _ParserState.READ_DATA_LEN_LO

            elif self._state == _ParserState.READ_DATA_LEN_LO:
                self._data_len = byte
                self._frame_buffer.append(byte)
                self._state = _ParserState.READ_DATA_LEN_HI

            elif self._state == _ParserState.READ_DATA_LEN_HI:
                self._data_len |= byte << 8
                self._frame_buffer.append(byte)
                # Check for oversized payload
                if self._data_len > self.max_payload:
                    logger.error(
                        "Oversized payload, resyncing",
                        data_len=self._data_len,
                        max_payload=self.max_payload,
                    )
                    framing_error = FramingError(
                        f"Payload size {self._data_len} exceeds maximum {self.max_payload}"
                    )
                    self._resync()
                    raise framing_error
                self._state = _ParserState.READ_SEQ_LO

            elif self._state == _ParserState.READ_SEQ_LO:
                self._seq = byte
                self._frame_buffer.append(byte)
                self._state = _ParserState.READ_SEQ_HI

            elif self._state == _ParserState.READ_SEQ_HI:
                self._seq |= byte << 8
                self._frame_buffer.append(byte)
                self._state = _ParserState.READ_CMD_ID

            elif self._state == _ParserState.READ_CMD_ID:
                self._cmd_id = byte
                self._frame_buffer.append(byte)
                self._data = bytearray()
                if self._data_len > 0:
                    self._state = _ParserState.READ_DATA
                else:
                    self._state = _ParserState.READ_CRC_LO

            elif self._state == _ParserState.READ_DATA:
                self._data.append(byte)
                self._frame_buffer.append(byte)
                if len(self._data) >= self._data_len:
                    self._state = _ParserState.READ_CRC_LO

            elif self._state == _ParserState.READ_CRC_LO:
                self._crc_lo = byte
                self._frame_buffer.append(byte)
                self._state = _ParserState.READ_CRC_HI

            elif self._state == _ParserState.READ_CRC_HI:
                self._crc_hi = byte
                self._frame_buffer.append(byte)
                self._state = _ParserState.VERIFY_CRC
                # Fall through to verify

            if self._state == _ParserState.VERIFY_CRC:
                # Verify CRC
                frame_without_crc = bytes(self._frame_buffer[:-CRC_LEN])
                expected_crc = self._crc_lo | (self._crc_hi << 8)
                actual_crc = crc16(frame_without_crc)

                if expected_crc != actual_crc:
                    frame_hex = bytes(self._frame_buffer).hex(sep=" ")
                    crc_error = CRCError(
                        expected=expected_crc,
                        actual=actual_crc,
                        frame_hex=frame_hex,
                    )
                    self._resync()
                    raise crc_error

                # Valid frame
                frame = Frame(
                    ctrl=self._ctrl,
                    seq=self._seq,
                    cmd_id=self._cmd_id,
                    data=bytes(self._data),
                )
                frames.append(frame)

                logger.debug(
                    "Frame received",
                    direction="rx",
                    cmd_id=f"0x{self._cmd_id:02X}",
                    seq=self._seq,
                    payload_len=len(self._data),
                    payload_bytes=bytes(self._data),
                )

                # Reset for next frame
                self._resync()

        return frames

    def _resync(self) -> None:
        """Reset parser to search for next frame start."""
        self._state = _ParserState.AWAIT_STX1
        self._ctrl = 0
        self._data_len = 0
        self._seq = 0
        self._cmd_id = 0
        self._data = bytearray()
        self._crc_lo = 0
        self._crc_hi = 0
        self._frame_buffer = bytearray()
