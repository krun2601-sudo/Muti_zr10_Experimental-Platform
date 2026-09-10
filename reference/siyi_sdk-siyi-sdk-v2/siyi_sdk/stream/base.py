# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Abstract base class for SIYI stream backends.

All concrete streaming backends implement this interface to provide a
consistent async API regardless of the underlying library used.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncGenerator

from .models import StreamConfig, StreamFrame


class AbstractStreamBackend(abc.ABC):
    """Common interface all streaming backends implement.

    Backends receive an RTSP URL via StreamConfig and are responsible for
    connection, frame decoding, reconnection, and clean shutdown.
    """

    def __init__(self, config: StreamConfig) -> None:
        """Initialise the backend with the given configuration.

        Args:
            config: Stream configuration including RTSP URL and tuning parameters.
        """
        self._config = config

    @abc.abstractmethod
    async def connect(self) -> None:
        """Open the RTSP connection.

        Raises:
            OSError: On unrecoverable network error.
            ImportError: If required library is not installed.
        """

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Release all resources. Idempotent — safe to call multiple times."""

    @abc.abstractmethod
    def frame_available(self) -> bool:
        """Return True if at least one decoded frame is ready to read.

        Returns:
            True when a frame can be retrieved via read_frame_nowait().
        """

    @abc.abstractmethod
    def read_frame_nowait(self) -> StreamFrame | None:
        """Return the newest decoded frame without blocking.

        Returns:
            Most recent StreamFrame, or None if no frame is available yet.
        """

    @abc.abstractmethod
    def frame_generator(self) -> AsyncGenerator[StreamFrame, None]:
        """Async generator that yields frames as they arrive.

        The generator must:
        - Handle reconnection internally per StreamConfig back-off policy.
        - Yield control via ``await asyncio.sleep(0)`` between frames.
        - Exit cleanly when disconnect() is called.

        Yields:
            StreamFrame objects in arrival order.
        """
