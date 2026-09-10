# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""HTTP media client for the SIYI camera web server (Chapter 7).

The SIYI gimbal camera exposes a REST API on port 82 for browsing and
downloading photos/videos stored on the TF card.  This module wraps
those three endpoints:

    GET /api/v1/getdirectories  — list date-based directories
    GET /api/v1/getmediacount   — file count in a directory
    GET /api/v1/getmedialist    — paginated file list with download URLs
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import structlog

from siyi_sdk.constants import DEFAULT_HTTP_PORT, DEFAULT_IP
from siyi_sdk.exceptions import TransportError
from siyi_sdk.models import MediaDirectory, MediaFile, MediaType

log: structlog.BoundLogger = structlog.get_logger(__name__)

_BASE_PATH = "//cgi-bin/media.cgi"


class MediaClient:
    """Async client for the SIYI camera web-server media API.

    All methods run the blocking ``urllib`` call in a thread-pool so they
    are safe to ``await`` from any asyncio event loop.

    Args:
        host: Camera IP address.
        port: Web-server port (default 82).
        timeout: HTTP request timeout in seconds.

    Example:
        >>> async with MediaClient("192.168.144.25") as media:
        ...     dirs = await media.list_directories(MediaType.IMAGES)
        ...     files = await media.list_files(MediaType.IMAGES, dirs[0].path)
        ...     print(files[0].url)
    """

    def __init__(
        self,
        host: str = DEFAULT_IP,
        port: int = DEFAULT_HTTP_PORT,
        timeout: float = 5.0,
    ) -> None:
        self._base = f"http://{host}:{port}{_BASE_PATH}"
        self._timeout = timeout

    async def __aenter__(self) -> MediaClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        url = f"{self._base}{path}?{urllib.parse.urlencode(params)}"
        log.debug("media_http_request", url=url)
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise TransportError(f"HTTP {exc.code} from camera media API: {exc.reason}") from exc
        except OSError as exc:
            raise TransportError(f"Camera media API unreachable: {exc}") from exc

        if not body.get("success", False):
            msg = body.get("message", "unknown error")
            raise TransportError(f"Camera media API error: {msg}")

        return body.get("data", {})

    async def _aget(self, path: str, params: dict[str, Any]) -> Any:
        return await asyncio.to_thread(self._get, path, params)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def list_directories(self, media_type: MediaType = MediaType.IMAGES) -> list[MediaDirectory]:
        """Return the date-based directories for the given media type.

        Args:
            media_type: ``MediaType.IMAGES`` or ``MediaType.VIDEOS``.

        Returns:
            List of :class:`~siyi_sdk.models.MediaDirectory` entries.

        Raises:
            TransportError: On HTTP failure or API-level error.
        """
        data = await self._aget("/api/v1/getdirectories", {"media_type": int(media_type)})
        return [MediaDirectory(name=d["name"], path=d["path"]) for d in data.get("directories", [])]

    async def get_media_count(
        self,
        media_type: MediaType = MediaType.IMAGES,
        path: str = "",
    ) -> int:
        """Return the number of files under *path* (or total if path is empty).

        Args:
            media_type: ``MediaType.IMAGES`` or ``MediaType.VIDEOS``.
            path: Directory path from :meth:`list_directories`. Empty string
                returns the total across all directories.

        Returns:
            File count.

        Raises:
            TransportError: On HTTP failure or API-level error.
        """
        data = await self._aget("/api/v1/getmediacount", {"media_type": int(media_type), "path": path})
        return int(data.get("count", 0))

    async def list_files(
        self,
        media_type: MediaType = MediaType.IMAGES,
        path: str = "",
        start: int = 0,
        count: int = 50,
    ) -> list[MediaFile]:
        """Return a paginated list of media files under *path*.

        Args:
            media_type: ``MediaType.IMAGES`` or ``MediaType.VIDEOS``.
            path: Directory path from :meth:`list_directories`. Empty string
                returns files across all directories.
            start: Zero-based start index.
            count: Maximum number of files to return.

        Returns:
            List of :class:`~siyi_sdk.models.MediaFile` entries, each
            carrying a ``name`` and a direct download ``url``.

        Raises:
            TransportError: On HTTP failure or API-level error.
        """
        data = await self._aget(
            "/api/v1/getmedialist",
            {"media_type": int(media_type), "path": path, "start": start, "count": count},
        )
        return [MediaFile(name=f["name"], url=f["url"]) for f in data.get("list", [])]

    async def list_all_files(
        self,
        media_type: MediaType = MediaType.IMAGES,
        path: str = "",
        page_size: int = 50,
    ) -> list[MediaFile]:
        """Fetch every file under *path* by auto-paginating.

        Args:
            media_type: ``MediaType.IMAGES`` or ``MediaType.VIDEOS``.
            path: Directory path. Empty string spans all directories.
            page_size: Files fetched per HTTP request.

        Returns:
            Complete list of :class:`~siyi_sdk.models.MediaFile` entries.

        Raises:
            TransportError: On HTTP failure or API-level error.
        """
        total = await self.get_media_count(media_type, path)
        files: list[MediaFile] = []
        start = 0
        while start < total:
            batch = await self.list_files(media_type, path, start=start, count=page_size)
            files.extend(batch)
            start += len(batch)
            if not batch:
                break
        return files
