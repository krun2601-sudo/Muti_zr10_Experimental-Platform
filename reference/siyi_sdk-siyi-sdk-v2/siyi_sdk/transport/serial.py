# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Serial transport implementation for SIYI SDK.

This module provides a serial transport using pyserial-asyncio.
Serial does not require heartbeat frames.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Final

import structlog

from ..constants import DEFAULT_BAUD
from .base import AbstractTransport

logger: Final = structlog.get_logger(__name__)


class SerialTransport(AbstractTransport):
    """Serial transport for SIYI SDK.

    This transport uses pyserial-asyncio for serial communication.
    Serial connections do not require heartbeat frames.

    Example:
        >>> transport = SerialTransport(device="/dev/ttyUSB0", baud=115200)
        >>> await transport.connect()
        >>> await transport.send(b"...")
        >>> async for chunk in transport.stream():
        ...     print(chunk)
    """

    def __init__(
        self,
        device: str,
        baud: int = DEFAULT_BAUD,
    ) -> None:
        """Initialize serial transport.

        Args:
            device: Serial device path (e.g., "/dev/ttyUSB0" or "COM3").
            baud: Baud rate (default: 115200).
        """
        self._device: str = device
        self._baud: int = baud
        self._connected: bool = False
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        """Establish serial connection.

        Raises:
            ConnectionError: If connection fails.
        """
        try:
            # Import here to make serial_asyncio an optional dependency
            import serial_asyncio

            self._reader, self._writer = await serial_asyncio.open_serial_connection(
                url=self._device,
                baudrate=self._baud,
                bytesize=8,
                parity="N",
                stopbits=1,
            )
            self._connected = True
            logger.info(
                "connected",
                transport="serial",
                device=self._device,
                baud=self._baud,
            )
        except (OSError, ImportError) as e:
            from ..exceptions import ConnectionError as ConnError

            raise ConnError(f"Failed to open serial port {self._device}: {e}") from e

    async def close(self) -> None:
        """Close the serial connection."""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as e:
                logger.warning("close_error", transport="serial", error=str(e))
            finally:
                self._writer = None
                self._reader = None

        self._connected = False
        logger.info("disconnected", transport="serial", device=self._device)

    async def send(self, data: bytes) -> None:
        """Send data over serial.

        Args:
            data: Bytes to send.

        Raises:
            NotConnectedError: If not connected.
            SendError: If send fails.
        """
        if not self._connected or not self._writer:
            from ..exceptions import NotConnectedError

            raise NotConnectedError("SerialTransport.send() called before connect()")

        try:
            self._writer.write(data)
            await self._writer.drain()
            logger.debug(
                "frame_tx",
                transport="serial",
                device=self._device,
                length=len(data),
                data_hex=data.hex(),
            )
        except (OSError, AttributeError) as e:
            from ..exceptions import SendError

            self._connected = False
            raise SendError(f"Serial send failed: {e}") from e

    async def stream(self) -> AsyncIterator[bytes]:
        """Yield received serial data chunks.

        Yields:
            bytes: Received data chunks (up to 4096 bytes each).
        """
        if not self._reader:
            return

        while self._connected:
            try:
                data = await self._reader.read(4096)
                if not data:
                    # EOF — connection closed
                    logger.info("eof_received", transport="serial")
                    self._connected = False
                    break

                logger.debug(
                    "frame_rx",
                    transport="serial",
                    device=self._device,
                    length=len(data),
                    data_hex=data.hex(),
                )
                yield data
            except (OSError, AttributeError) as e:
                logger.error("stream_error", transport="serial", error=str(e))
                self._connected = False
                break

    @property
    def is_connected(self) -> bool:
        """Return True if connected.

        Returns:
            bool: Connection state.
        """
        return self._connected

    @property
    def supports_heartbeat(self) -> bool:
        """Return False (serial does not require heartbeat).

        Returns:
            bool: Always False for serial.
        """
        return False
