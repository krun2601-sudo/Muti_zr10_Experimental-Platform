# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Pure-async RTSP backend using aiortsp + PyAV software decode.

Opens an RTSP session via aiortsp (no system libraries required), reads RTP
packets, and decodes them with PyAV's libavcodec wrapper. Suitable for CI,
Docker, and other environments where GStreamer is unavailable.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncGenerator
from typing import Final

import structlog

try:
    import aiortsp
    import av

    _AIORTSP_AVAILABLE = True
except ImportError:
    _AIORTSP_AVAILABLE = False

from .base import AbstractStreamBackend
from .models import StreamConfig, StreamFrame

_log: Final = structlog.get_logger(__name__)

_RECONNECT_DELAY_CAP: Final[float] = 30.0


class AiortspBackend(AbstractStreamBackend):
    """Pure-Python async RTSP backend using aiortsp and PyAV.

    All decoding happens inside asyncio tasks; no extra threads are required.

    Args:
        config: Stream configuration.

    Raises:
        ImportError: If aiortsp or av packages are not installed.
    """

    BACKEND_NAME: Final = "aiortsp"

    def __init__(self, config: StreamConfig) -> None:
        """Initialise the aiortsp backend.

        Args:
            config: Stream configuration.

        Raises:
            ImportError: If aiortsp or PyAV is not installed.
        """
        if not _AIORTSP_AVAILABLE:
            raise ImportError(
                "aiortsp and av (PyAV) are required for AiortspBackend. "
                "Install with: pip install aiortsp av"
            )
        super().__init__(config)
        self._connected = False
        self._stop_event = asyncio.Event()
        self._latest: StreamFrame | None = None

    async def connect(self) -> None:
        """Mark the backend as ready to stream.

        The actual RTSP session is opened inside frame_generator().
        """
        self._stop_event.clear()
        self._connected = True
        _log.info("aiortsp_backend_ready", url=self._config.rtsp_url)

    async def disconnect(self) -> None:
        """Signal the frame generator to stop."""
        self._stop_event.set()
        self._connected = False
        _log.info("aiortsp_backend_disconnected")

    def frame_available(self) -> bool:
        """Return True if a frame has been decoded.

        Returns:
            True when at least one frame has been decoded since connect().
        """
        return self._latest is not None

    def read_frame_nowait(self) -> StreamFrame | None:
        """Return the most recently decoded frame without blocking.

        Returns:
            Most recent StreamFrame, or None.
        """
        return self._latest

    async def frame_generator(self) -> AsyncGenerator[StreamFrame, None]:
        """Async generator yielding decoded video frames.

        Opens the RTSP session, reads RTP packets, decodes with PyAV, and
        yields StreamFrame objects. Reconnects with exponential back-off on
        any network or decode error.

        Yields:
            StreamFrame objects as they are decoded.
        """
        delay = self._config.reconnect_delay
        attempt = 0

        while not self._stop_event.is_set():
            attempt += 1
            try:
                async with aiortsp.RTSPReader(self._config.rtsp_url) as reader:
                    _log.info(
                        "aiortsp_connected",
                        url=self._config.rtsp_url,
                        attempt=attempt,
                    )
                    delay = self._config.reconnect_delay  # reset on success

                    codec_ctx = av.CodecContext.create("h264", "r")

                    async for rtp_pkt in reader.iter_packets():
                        if self._stop_event.is_set():
                            break

                        pkt = av.Packet(rtp_pkt.data)
                        try:
                            frames = codec_ctx.decode(pkt)
                        except av.AVError:
                            continue

                        for av_frame in frames:
                            bgr_frame = av_frame.to_ndarray(format="bgr24")
                            h, w = bgr_frame.shape[:2]
                            sf = StreamFrame(
                                frame=bgr_frame,
                                timestamp=time.monotonic(),
                                width=w,
                                height=h,
                                backend=self.BACKEND_NAME,
                            )
                            self._latest = sf

                            _log.debug(
                                "aiortsp_frame_decoded",
                                backend=self.BACKEND_NAME,
                                width=w,
                                height=h,
                                timestamp=sf.timestamp,
                            )
                            await asyncio.sleep(0)
                            yield sf

            except Exception as exc:
                if self._stop_event.is_set():
                    break
                _log.warning(
                    "aiortsp_reconnect",
                    attempt=attempt,
                    delay=delay,
                    exc=type(exc).__name__,
                    msg=str(exc),
                )
                if (
                    self._config.max_reconnect_attempts > 0
                    and attempt >= self._config.max_reconnect_attempts
                ):
                    _log.error(
                        "aiortsp_max_reconnects_exceeded",
                        max_attempts=self._config.max_reconnect_attempts,
                    )
                    break
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                delay = min(delay * 1.5, _RECONNECT_DELAY_CAP)
