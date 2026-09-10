# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""OpenCV-based RTSP backend using a background daemon thread.

Uses cv2.VideoCapture with the FFmpeg backend. A daemon thread runs a tight
cap.read() loop and posts frames to an asyncio.Queue for async consumption.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections import deque
from collections.abc import AsyncGenerator
from typing import Final

import structlog

try:
    import cv2

    _OPENCV_AVAILABLE = True
except ImportError:
    _OPENCV_AVAILABLE = False

from .base import AbstractStreamBackend
from .models import StreamConfig, StreamFrame

_log: Final = structlog.get_logger(__name__)

# Cap on exponential back-off in seconds.
_RECONNECT_DELAY_CAP: Final[float] = 30.0


class OpenCVBackend(AbstractStreamBackend):
    """OpenCV + threading RTSP backend.

    A background daemon thread runs cv2.VideoCapture and feeds frames into an
    asyncio.Queue. The main loop consumes frames via frame_generator().

    Args:
        config: Stream configuration.

    Raises:
        ImportError: If opencv-python is not installed.
    """

    BACKEND_NAME: Final = "opencv"

    def __init__(self, config: StreamConfig) -> None:
        """Initialise the OpenCV backend.

        Args:
            config: Stream configuration.

        Raises:
            ImportError: If opencv-python is not installed.
        """
        if not _OPENCV_AVAILABLE:
            raise ImportError(
                "opencv-python is required for OpenCVBackend. "
                "Install it with: pip install opencv-python"
            )
        super().__init__(config)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._latest: deque[StreamFrame] = deque(maxlen=1)
        self._queue: asyncio.Queue[StreamFrame] | None = None
        self._stop_event = threading.Event()

    async def connect(self) -> None:
        """Start the background capture thread.

        Captures the running event loop, creates the inter-thread queue, and
        starts the daemon thread.
        """
        self._stop_event.clear()
        self._loop = asyncio.get_event_loop()
        self._queue = asyncio.Queue(maxsize=1)

        self._thread = threading.Thread(
            target=self._capture_loop,
            name="siyi-opencv-capture",
            daemon=True,
        )
        self._thread.start()
        _log.info(
            "opencv_backend_connected",
            url=self._config.rtsp_url,
            transport=self._config.transport,
        )

    async def disconnect(self) -> None:
        """Stop the capture thread and release resources."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        _log.info("opencv_backend_disconnected")

    def frame_available(self) -> bool:
        """Return True if a frame is buffered.

        Returns:
            True when the latest deque contains a frame.
        """
        return bool(self._latest)

    def read_frame_nowait(self) -> StreamFrame | None:
        """Return the most recently decoded frame without blocking.

        Returns:
            Most recent StreamFrame, or None if none available.
        """
        return self._latest[-1] if self._latest else None

    async def frame_generator(self) -> AsyncGenerator[StreamFrame, None]:
        """Yield frames from the background capture thread.

        Waits on the asyncio queue that the capture thread posts to. Exits when
        disconnect() is called (stop_event is set).

        Yields:
            StreamFrame objects as they are decoded.
        """
        if self._queue is None:
            return
        while not self._stop_event.is_set():
            try:
                frame = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                yield frame
            except asyncio.TimeoutError:
                continue

    def _capture_loop(self) -> None:
        """Background thread: open VideoCapture, read frames, handle reconnects."""
        delay = self._config.reconnect_delay
        attempt = 0

        while not self._stop_event.is_set():
            attempt += 1
            # fflags=nobuffer + flags=low_delay + max_delay=0 tell FFmpeg to hand
            # frames to the application as soon as they're decoded rather than
            # accumulating them in a jitter buffer.
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                f"rtsp_transport;{self._config.transport}"
                "|fflags;nobuffer"
                "|flags;low_delay"
                "|max_delay;0"
                "|framedrop;1"
            )

            cap: cv2.VideoCapture = cv2.VideoCapture(
                self._config.rtsp_url,
                cv2.CAP_FFMPEG,
            )
            cap.set(cv2.CAP_PROP_BUFFERSIZE, self._config.buffer_size)

            if not cap.isOpened():
                _log.warning(
                    "opencv_open_failed",
                    attempt=attempt,
                    delay=delay,
                    url=self._config.rtsp_url,
                )
                cap.release()
                self._stop_event.wait(timeout=delay)
                delay = min(delay * 1.5, _RECONNECT_DELAY_CAP)
                if (
                    self._config.max_reconnect_attempts > 0
                    and attempt >= self._config.max_reconnect_attempts
                ):
                    _log.error(
                        "opencv_max_reconnects_exceeded",
                        max_attempts=self._config.max_reconnect_attempts,
                    )
                    break
                continue

            _log.info("opencv_capture_opened", url=self._config.rtsp_url, attempt=attempt)
            delay = self._config.reconnect_delay  # reset on success

            self._read_loop(cap)
            cap.release()

            if self._stop_event.is_set():
                break

            _log.warning(
                "opencv_stream_lost",
                attempt=attempt,
                reconnect_delay=delay,
            )
            self._stop_event.wait(timeout=delay)
            delay = min(delay * 1.5, _RECONNECT_DELAY_CAP)

    def _read_loop(self, cap: cv2.VideoCapture) -> None:
        """Inner frame-reading loop for an open VideoCapture.

        Args:
            cap: Open cv2.VideoCapture instance.
        """
        loop = self._loop
        queue = self._queue
        if loop is None or queue is None:
            return

        while not self._stop_event.is_set():
            ok, img = cap.read()
            if not ok or img is None:
                break

            h, w = img.shape[:2]
            sf = StreamFrame(
                frame=img,
                timestamp=time.monotonic(),
                width=w,
                height=h,
                backend=self.BACKEND_NAME,
            )
            self._latest.append(sf)

            _log.debug(
                "opencv_frame_decoded",
                backend=self.BACKEND_NAME,
                width=w,
                height=h,
                timestamp=sf.timestamp,
            )

            # Drop frame if queue is full — latest always wins.
            # The exception must be caught inside the event-loop callback, not here,
            # because call_soon_threadsafe returns immediately without raising.
            def _put(q: asyncio.Queue[StreamFrame] = queue, f: StreamFrame = sf) -> None:
                try:
                    q.put_nowait(f)
                except asyncio.QueueFull:
                    pass

            loop.call_soon_threadsafe(_put)
