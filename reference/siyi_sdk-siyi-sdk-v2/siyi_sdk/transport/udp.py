# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""UDP transport implementation for SIYI SDK.

This module provides a UDP transport using asyncio.DatagramProtocol.
UDP does not require heartbeat frames.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Final

import structlog

from ..constants import DEFAULT_IP, DEFAULT_UDP_PORT
from .base import AbstractTransport

if TYPE_CHECKING:
    from asyncio import DatagramTransport

logger: Final = structlog.get_logger(__name__)


class _DatagramProtocol(asyncio.DatagramProtocol):
    """Internal datagram protocol handler."""

    def __init__(self, queue: asyncio.Queue[bytes]) -> None:
        """Initialize the protocol.

        Args:
            queue: Queue to push received datagrams into.
        """
        self._queue = queue

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle received datagram.

        Args:
            data: Received bytes.
            addr: Source address tuple.
        """
        try:
            self._queue.put_nowait(data)
        except asyncio.QueueFull:
            logger.warning("udp_queue_full", dropped_bytes=len(data))


class UDPTransport(AbstractTransport):
    """UDP transport for SIYI SDK.

    This transport uses asyncio's DatagramProtocol to send/receive UDP packets.
    No heartbeat is required for UDP connections.

    Example:
        >>> transport = UDPTransport(ip="192.168.144.25", port=37260)
        >>> await transport.connect()
        >>> await transport.send(b"...")
        >>> async for chunk in transport.stream():
        ...     print(chunk)
    """

    def __init__(
        self,
        ip: str = DEFAULT_IP,
        port: int = DEFAULT_UDP_PORT,
        *,
        bind_port: int | None = None,
    ) -> None:
        """Initialize UDP transport.

        Args:
            ip: Target gimbal IP address.
            port: Target UDP port.
            bind_port: Optional local port to bind to. If None, use ephemeral port.
        """
        self._ip: str = ip
        self._port: int = port
        self._bind_port: int | None = bind_port
        self._connected: bool = False
        self._transport: DatagramTransport | None = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        self._stream_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """Establish UDP connection.

        Raises:
            ConnectionError: If endpoint creation fails.
        """
        loop = asyncio.get_running_loop()

        try:
            local_addr = ("0.0.0.0", self._bind_port) if self._bind_port else None
            transport, _ = await loop.create_datagram_endpoint(
                lambda: _DatagramProtocol(self._queue),
                remote_addr=(self._ip, self._port),
                local_addr=local_addr,
            )
            self._transport = transport
            self._connected = True
            logger.info(
                "connected",
                transport="udp",
                peer=f"{self._ip}:{self._port}",
                local_port=self._bind_port or "ephemeral",
            )
        except OSError as e:
            from ..exceptions import ConnectionError as ConnError

            raise ConnError(f"Failed to create UDP endpoint: {e}") from e

    async def close(self) -> None:
        """Close the UDP connection."""
        if self._transport:
            self._transport.close()
            self._transport = None

        self._connected = False

        # Drain the queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        logger.info("disconnected", transport="udp")

    async def send(self, data: bytes) -> None:
        """Send UDP datagram.

        Args:
            data: Bytes to send.

        Raises:
            NotConnectedError: If not connected.
            SendError: If send fails.
        """
        if not self._connected or not self._transport:
            from ..exceptions import NotConnectedError

            raise NotConnectedError("UDPTransport.send() called before connect()")

        try:
            self._transport.sendto(data)
            logger.debug(
                "frame_tx",
                transport="udp",
                peer=f"{self._ip}:{self._port}",
                length=len(data),
                data_hex=data.hex(),
            )
        except OSError as e:
            from ..exceptions import SendError

            raise SendError(f"UDP send failed: {e}") from e

    async def stream(self) -> AsyncIterator[bytes]:
        """Yield received UDP datagrams.

        Yields:
            bytes: Received datagram data.
        """
        while self._connected:
            try:
                data = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                logger.debug(
                    "frame_rx",
                    transport="udp",
                    length=len(data),
                    data_hex=data.hex(),
                )
                yield data
            except asyncio.TimeoutError:
                continue

    @property
    def is_connected(self) -> bool:
        """Return True if connected.

        Returns:
            bool: Connection state.
        """
        return self._connected

    @property
    def supports_heartbeat(self) -> bool:
        """Return False (UDP does not require heartbeat).

        Returns:
            bool: Always False for UDP.
        """
        return False
