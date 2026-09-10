# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Abstract base class for all SIYI SDK transports.

This module defines the AbstractTransport ABC that all concrete transport
implementations must inherit from. It provides a common interface for UDP,
TCP, Serial, and Mock transports.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from typing import TypeAlias

# Type alias for unsubscribe callbacks
Unsubscribe: TypeAlias = Callable[[], None]


class AbstractTransport(ABC):
    """Abstract base class for transport implementations.

    All transport implementations (UDP, TCP, Serial, Mock) must implement
    this interface to provide a consistent API for the client layer.

    Transport implementations are responsible for:
    - Establishing and maintaining connections
    - Sending raw bytes to the device
    - Streaming received bytes to consumers
    - Managing connection state
    - Reporting heartbeat support capabilities

    Raises:
        ConnectionError: When connect() fails to establish a connection.
        NotConnectedError: When send() is called before connect().
        SendError: When send() encounters an OS-level failure.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the device.

        This method must be called before any other operations.
        Implementations should set internal state to track connection status.

        Raises:
            ConnectionError: If connection cannot be established.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the connection and release resources.

        This method should gracefully shut down the transport, cancel any
        pending operations, and drain/close any queues or streams.

        After calling this method, the transport should report is_connected=False.
        """
        ...

    @abstractmethod
    async def send(self, data: bytes) -> None:
        """Send raw bytes to the device.

        Args:
            data: Raw bytes to transmit.

        Raises:
            NotConnectedError: If called before connect() or after close().
            SendError: If the underlying transport encounters an OS error.
        """
        ...

    @abstractmethod
    def stream(self) -> AsyncIterator[bytes]:
        """Return an async iterator yielding received bytes.

        The iterator yields chunks of bytes as they arrive from the device.
        Chunk size is transport-dependent.

        Yields:
            bytes: Received data chunks.

        Note:
            The iterator should terminate when the transport is closed.
        """
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the transport is currently connected.

        Returns:
            bool: Connection state.
        """
        ...

    @property
    @abstractmethod
    def supports_heartbeat(self) -> bool:
        """Return True if this transport requires periodic heartbeat frames.

        TCP transports return True (requires 1 Hz heartbeat).
        UDP and Serial transports return False (no heartbeat required).

        Returns:
            bool: True if heartbeat is supported/required.
        """
        ...
