# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Mock transport implementation for testing.

This module provides a MockTransport for testing that allows queuing
responses and capturing sent frames without requiring a real device.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Final

import structlog

from .base import AbstractTransport

logger: Final = structlog.get_logger(__name__)


class MockTransport(AbstractTransport):
    r"""Mock transport for testing without a real device.

    This transport implementation queues responses in FIFO order and
    captures all sent frames for verification in tests.

    Example:
        >>> transport = MockTransport()
        >>> await transport.connect()
        >>> transport.queue_response(b"\x55\x66...")
        >>> await transport.send(b"\x01\x02\x03")
        >>> async for chunk in transport.stream():
        ...     print(chunk)  # b"\x55\x66..."
        >>> assert transport.sent_frames == [b"\x01\x02\x03"]
    """

    def __init__(self, *, supports_heartbeat: bool = False) -> None:
        """Initialize the mock transport.

        Args:
            supports_heartbeat: If True, simulate TCP-like heartbeat support.
                               If False (default), simulate UDP/Serial behavior.
        """
        self._connected: bool = False
        self._supports_heartbeat: bool = supports_heartbeat
        self._response_queue: asyncio.Queue[bytes | Exception] = asyncio.Queue()
        self._sent_frames: list[bytes] = []
        self._stream_cancelled: bool = False

    async def connect(self) -> None:
        """Establish mock connection.

        This sets the internal connection state to True without performing
        any actual network operations.
        """
        self._connected = True
        self._stream_cancelled = False
        logger.info("connected", transport="mock", supports_heartbeat=self._supports_heartbeat)

    async def close(self) -> None:
        """Close the mock connection.

        This sets the internal connection state to False and signals the
        stream iterator to terminate.
        """
        import contextlib

        self._connected = False
        self._stream_cancelled = True
        # Put a sentinel to wake up any waiting stream() consumers
        with contextlib.suppress(asyncio.QueueFull):
            self._response_queue.put_nowait(StopAsyncIteration())
        logger.info("disconnected", transport="mock")

    async def send(self, data: bytes) -> None:
        """Record sent data.

        Args:
            data: Bytes to send (captured for test verification).

        Raises:
            NotConnectedError: If not connected.
        """
        if not self._connected:
            from ..exceptions import NotConnectedError

            raise NotConnectedError("MockTransport.send() called before connect()")

        self._sent_frames.append(data)
        logger.debug(
            "frame_tx",
            transport="mock",
            length=len(data),
            data_hex=data.hex(),
        )

    async def stream(self) -> AsyncIterator[bytes]:
        """Yield queued responses in FIFO order.

        Yields:
            bytes: Response data chunks.

        Raises:
            Any exception queued via queue_error().
        """
        while not self._stream_cancelled:
            try:
                item = await asyncio.wait_for(self._response_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            # Check for stream cancellation sentinel
            if isinstance(item, StopAsyncIteration):
                break

            # Re-raise queued exceptions
            if isinstance(item, Exception):
                logger.debug("stream_error", transport="mock", exc=type(item).__name__)
                raise item

            # Yield bytes
            logger.debug(
                "frame_rx",
                transport="mock",
                length=len(item),
                data_hex=item.hex(),
            )
            yield item

    @property
    def is_connected(self) -> bool:
        """Return True if connected.

        Returns:
            bool: Connection state.
        """
        return self._connected

    @property
    def supports_heartbeat(self) -> bool:
        """Return heartbeat support flag.

        Returns:
            bool: True if heartbeat is supported (TCP simulation mode).
        """
        return self._supports_heartbeat

    def queue_response(self, data: bytes) -> None:
        """Queue a response to be yielded by stream().

        Args:
            data: Response bytes to yield.
        """
        self._response_queue.put_nowait(data)
        logger.debug("queued_response", transport="mock", length=len(data))

    def queue_error(self, exc: Exception) -> None:
        """Queue an exception to be raised by stream().

        Args:
            exc: Exception to raise when stream() consumes this entry.
        """
        self._response_queue.put_nowait(exc)
        logger.debug("queued_error", transport="mock", exc=type(exc).__name__)

    @property
    def sent_frames(self) -> list[bytes]:
        """Return a copy of all frames sent via send().

        Returns:
            list[bytes]: Defensive copy of sent frames.
        """
        return self._sent_frames.copy()
