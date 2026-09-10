---
name: siyi-sdk-video-streaming
description: Implements the siyi_sdk.stream sub-package — RTSP video streaming with OpenCV, GStreamer, and aiortsp backends — plus full tests, examples, and documentation updates.
model: claude-sonnet-4-6
color: pink
---

### Context

You are implementing the video/camera streaming feature for the SIYI SDK Python package located at the **current working directory** (the repo root). All phases 0–8 are already complete. The package is production-quality: it passes `hatch run lint:lint`, `hatch run lint:typecheck`, and `pytest tests/ --cov=siyi_sdk --cov-fail-under=90`.

Your job is to add `siyi_sdk/stream/` — a new sub-package that provides RTSP video reception from SIYI cameras — without breaking any existing tests, linting, or type-checking.

Read the full implementation plan before writing a single line of code:

```
docs/video_streaming_plan.md
```

Also read these existing files to understand the package conventions before coding:

- `siyi_sdk/__init__.py` — see how public API is exported
- `siyi_sdk/client.py` — coding style, logging, docstrings, type annotations
- `siyi_sdk/models.py` — dataclass patterns (frozen, slots)
- `siyi_sdk/exceptions.py` — exception hierarchy pattern
- `siyi_sdk/transport/base.py` — ABC pattern used in this codebase
- `pyproject.toml` — toolchain config (ruff, mypy strict, black, hatch envs, optional deps syntax)
- `tests/test_client.py` — test style, MockTransport usage, pytest-asyncio patterns
- `.claude/agents/05_client_api.md` and `.claude/agents/06_tests_and_integration.md` — coding and logging standards that apply here too

---

### RTSP Endpoint Reference (from official SIYI manuals)

SIYI cameras split into two generations based on the ZT30 release.

**New-generation cameras (ZT30, ZT6, and later):**

| Stream | RTSP URL |
|--------|----------|
| Main | `rtsp://192.168.144.25:8554/video1` |
| Sub | `rtsp://192.168.144.25:8554/video2` |
| AI Camera | `rtsp://192.168.144.60:554/video0` |

**Old-generation cameras (ZR30, ZR10, A8 Mini, A2 Mini, R1M):**

| Stream | RTSP URL |
|--------|----------|
| Main (only) | `rtsp://192.168.144.25:8554/main.264` |

> Old-gen cameras expose only one RTSP stream. Sub-stream access on old-gen uses the
> SIYI FPV private UDP protocol (ports 37255/37256) — do NOT implement that protocol here.

**SIYI FPV private protocol UDP ports (documented, not implemented):**
- Camera 1 Main: `192.168.144.25:37256`
- Camera 1 Sub: `192.168.144.25:37255`

**Default camera IP:** `192.168.144.25`. The `SIYIClient` stores the connected host in `self._host`.

---

### Design Principles

1. **Async-native** — `SIYIStream` is asyncio-compatible. No hidden blocking on the event loop.
2. **Clean separation** — streaming lives in `siyi_sdk/stream/` only. Do not modify `client.py` business logic; only add the `create_stream()` factory method.
3. **Backend-agnostic public API** — same `SIYIStream` interface regardless of backend.
4. **Optional heavy dependencies** — GStreamer (`PyGObject`) and aiortsp+PyAV are optional extras. OpenCV is the zero-extra-dep fallback. Guard all imports with `try/except ImportError`.
5. **Frame delivery via callbacks** — mirrors the existing `on_attitude` / `on_laser_distance` callback pattern in `SIYIClient`.
6. **Auto-reconnection with exponential back-off** — cap at 30 s.
7. **No memory growth** — use `deque(maxlen=1)` or `asyncio.Queue(maxsize=1)` with `put_nowait` + drop-on-full to ensure only the newest frame is held.

---

### Module Layout to Create

```
siyi_sdk/
└── stream/
    ├── __init__.py          # Public exports
    ├── models.py            # CameraGeneration, StreamBackend, StreamConfig, StreamFrame, build_rtsp_url
    ├── base.py              # AbstractStreamBackend ABC
    ├── opencv_backend.py    # OpenCV + threading backend
    ├── gstreamer_backend.py # GStreamer + appsink backend (guarded import)
    ├── aiortsp_backend.py   # aiortsp + PyAV backend (guarded import)
    └── stream.py            # SIYIStream — the public async API

tests/
└── stream/
    ├── __init__.py
    ├── test_models.py       # StreamConfig, StreamFrame, build_rtsp_url, CameraGeneration
    ├── test_stream.py       # SIYIStream lifecycle, callbacks, reconnect (mock backend)
    ├── test_opencv_backend.py
    ├── test_gstreamer_backend.py
    └── test_aiortsp_backend.py

examples/
    ├── rtsp_opencv_new_gen.py      # ZT30/ZT6 main stream via OpenCV
    ├── rtsp_opencv_old_gen.py      # ZR10/A8Mini via OpenCV (old-gen URL)
    ├── rtsp_gstreamer.py           # GStreamer low-latency pipeline
    ├── rtsp_sub_stream.py          # New-gen sub stream /video2
    ├── rtsp_record.py              # Save stream to MP4
    └── rtsp_with_control.py        # Simultaneous gimbal control + video
```

---

### Phase A — `siyi_sdk/stream/models.py`

Implement these public types exactly:

```python
from __future__ import annotations
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal
import numpy as np

class CameraGeneration(str, Enum):
    """RTSP URL scheme generation boundary is ZT30."""
    OLD = "old"   # ZR30, ZR10, A8 Mini, A2 Mini, R1M → /main.264
    NEW = "new"   # ZT30, ZT6 and later → /video1, /video2

CAMERA_GENERATION_MAP: dict[str, CameraGeneration] = {
    "zt30": CameraGeneration.NEW,
    "zt6":  CameraGeneration.NEW,
    "zr30": CameraGeneration.OLD,
    "zr10": CameraGeneration.OLD,
    "a8":   CameraGeneration.OLD,
    "a2":   CameraGeneration.OLD,
    "r1m":  CameraGeneration.OLD,
}

class StreamBackend(str, Enum):
    AUTO       = "auto"        # probe GStreamer → aiortsp → OpenCV
    OPENCV     = "opencv"
    GSTREAMER  = "gstreamer"
    AIORTSP    = "aiortsp"

@dataclass
class StreamConfig:
    rtsp_url: str
    backend: StreamBackend = StreamBackend.AUTO
    transport: Literal["tcp", "udp"] = "tcp"   # RTSP transport; TCP preferred for stability
    latency_ms: int = 100          # GStreamer rtspsrc latency knob
    reconnect_delay: float = 2.0   # initial back-off seconds
    max_reconnect_attempts: int = 0  # 0 = unlimited
    buffer_size: int = 1           # OpenCV CAP_PROP_BUFFERSIZE

@dataclass
class StreamFrame:
    frame: np.ndarray              # BGR (H×W×3)
    timestamp: float               # time.monotonic() at decode
    width: int
    height: int
    backend: str                   # which backend produced this frame

def build_rtsp_url(
    host: str = "192.168.144.25",
    stream: Literal["main", "sub"] = "main",
    generation: CameraGeneration = CameraGeneration.NEW,
) -> str:
    """Return the correct RTSP URL for the given host, stream slot, and camera generation.

    Old-gen cameras (ZR30/ZR10/A8Mini/A2Mini/R1M):
        rtsp://<host>:8554/main.264  (main only; sub not available via RTSP)
    New-gen cameras (ZT30/ZT6 and later):
        rtsp://<host>:8554/video1   (main)
        rtsp://<host>:8554/video2   (sub)
    """
    if generation is CameraGeneration.OLD:
        return f"rtsp://{host}:8554/main.264"
    path = "video1" if stream == "main" else "video2"
    return f"rtsp://{host}:8554/{path}"
```

Rules:
- `StreamConfig` must validate that `latency_ms >= 0`, `reconnect_delay > 0`, `buffer_size >= 1`. Raise `ValueError` with clear messages on violation.
- `StreamFrame` is NOT frozen (numpy arrays are not hashable), but give it `__eq__` by value if needed for tests.

---

### Phase B — `siyi_sdk/stream/base.py`

```python
from __future__ import annotations
import abc
from collections.abc import AsyncIterator
from .models import StreamConfig, StreamFrame

class AbstractStreamBackend(abc.ABC):
    """Common interface all streaming backends implement."""

    def __init__(self, config: StreamConfig) -> None:
        self._config = config

    @abc.abstractmethod
    async def connect(self) -> None:
        """Open the RTSP connection. Raise on unrecoverable error."""

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Release all resources. Idempotent."""

    @abc.abstractmethod
    def frame_available(self) -> bool:
        """Return True if at least one decoded frame is ready."""

    @abc.abstractmethod
    def read_frame_nowait(self) -> StreamFrame | None:
        """Return the newest frame without blocking, or None."""

    @abc.abstractmethod
    async def frame_generator(self) -> AsyncIterator[StreamFrame]:
        """Async generator that yields frames as they arrive.

        Must handle reconnection internally per StreamConfig back-off policy.
        Must yield control (await asyncio.sleep(0)) between frames.
        Exits cleanly when disconnect() is called.
        """
```

Also define a `MockStreamBackend` in `base.py` (or `tests/stream/conftest.py`) that:
- Accepts a list of pre-built `StreamFrame` objects at construction.
- `connect()` / `disconnect()` are no-ops.
- `frame_generator()` yields each frame in sequence with `await asyncio.sleep(0)` between them, then stops.

---

### Phase C — `siyi_sdk/stream/opencv_backend.py`

```python
"""OpenCV-based RTSP backend using a background daemon thread."""
from __future__ import annotations
import asyncio
import os
import threading
import time
from collections import deque

try:
    import cv2
    _OPENCV_AVAILABLE = True
except ImportError:
    _OPENCV_AVAILABLE = False

from .base import AbstractStreamBackend
from .models import StreamConfig, StreamFrame

class OpenCVBackend(AbstractStreamBackend):
    BACKEND_NAME = "opencv"

    def __init__(self, config: StreamConfig) -> None:
        if not _OPENCV_AVAILABLE:
            raise ImportError("opencv-python is required for OpenCVBackend. pip install opencv-python")
        super().__init__(config)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._latest: deque[StreamFrame] = deque(maxlen=1)
        self._queue: asyncio.Queue[StreamFrame] | None = None
        self._stop_event = threading.Event()
```

Implementation notes:
- `connect()` captures `asyncio.get_event_loop()`, creates `asyncio.Queue(maxsize=1)`, starts daemon thread.
- Thread body: sets `OPENCV_FFMPEG_CAPTURE_OPTIONS` env var to `rtsp_transport;tcp` (or `udp`) then calls `cv2.VideoCapture(url, cv2.CAP_FFMPEG)`. Sets `CAP_PROP_BUFFERSIZE=config.buffer_size`. Tight `cap.read()` loop. On frame: wrap in `StreamFrame`, store in `deque`, post to queue via `loop.call_soon_threadsafe(queue.put_nowait, frame)` — if queue full, just drop (latest frame wins). On read failure: close cap, exponential sleep, reopen. Exit when `_stop_event.set()`.
- `disconnect()` sets `_stop_event`, joins thread with timeout=5 s.
- `frame_generator()` is an `async def` that `await self._queue.get()` in a loop until `_stop_event`.
- Log all connect/disconnect/error events via `structlog.get_logger(__name__)`.

---

### Phase D — `siyi_sdk/stream/gstreamer_backend.py`

Guard the entire module with `try: import gi; gi.require_version(...)`.

```python
"""GStreamer RTSP backend using appsink — lowest latency, hardware acceleration."""
from __future__ import annotations
import asyncio
import threading
import time
from collections import deque

try:
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import GLib, Gst  # type: ignore[import]
    Gst.init(None)
    _GST_AVAILABLE = True
except Exception:
    _GST_AVAILABLE = False

from .base import AbstractStreamBackend
from .models import StreamConfig, StreamFrame

_H264_PIPELINE = (
    "rtspsrc location={url} protocols={proto} latency={latency} buffer-mode=slave "
    "! queue max-size-buffers=1 leaky=downstream "
    "! rtph264depay ! h264parse "
    "! decodebin "
    "! videoconvert "
    "! video/x-raw,format=BGR "
    "! appsink name=sink emit-signals=true max-buffers=1 drop=true"
)

_H265_PIPELINE = (
    "rtspsrc location={url} protocols={proto} latency={latency} buffer-mode=slave "
    "! queue max-size-buffers=1 leaky=downstream "
    "! rtph265depay ! h265parse "
    "! decodebin "
    "! videoconvert "
    "! video/x-raw,format=BGR "
    "! appsink name=sink emit-signals=true max-buffers=1 drop=true"
)
```

Implementation notes:
- `connect()`: build pipeline string (default H.264; expose `codec: Literal["h264","h265"] = "h264"` param in `StreamConfig` optionally, or detect from URL `.264` suffix). Start GLib.MainLoop in a daemon thread.
- Wire `appsink.connect("new-sample", self._on_sample)` before setting pipeline to PLAYING.
- `_on_sample`: extract `Gst.Buffer`, map to numpy (use `Gst.Buffer.map(Gst.MapFlags.READ)`, then `np.frombuffer(...)`), post to asyncio loop via `call_soon_threadsafe`.
- Bus watch for `ERROR` and `EOS` messages → trigger reconnect.
- `disconnect()`: set pipeline to NULL, quit GLib.MainLoop, join thread.
- `frame_generator()`: same pattern as OpenCV — await from asyncio.Queue.
- If `_GST_AVAILABLE` is False, `__init__` raises `ImportError` with install instructions.

---

### Phase E — `siyi_sdk/stream/aiortsp_backend.py`

Guard entire module with `try: import aiortsp; import av`.

```python
"""Pure-async RTSP backend using aiortsp + PyAV software decode."""
from __future__ import annotations
import asyncio
import time

try:
    import aiortsp  # type: ignore[import]
    import av       # type: ignore[import]
    _AIORTSP_AVAILABLE = True
except ImportError:
    _AIORTSP_AVAILABLE = False

from .base import AbstractStreamBackend
from .models import StreamConfig, StreamFrame
```

Implementation notes:
- `frame_generator()` is the primary entry point; `connect()` / `disconnect()` manage connection state flags.
- Open `aiortsp.RTSPReader(url)` as async context manager. Read RTP packets. Detect H.264 or H.265 from SDP. Feed into `av.CodecContext.create("h264", "r")` or `"hevc"`. `codec.decode(av.Packet(data))` yields `av.VideoFrame` objects. Convert to numpy BGR. Yield `StreamFrame`.
- Reconnect loop with back-off: same pattern as OpenCV thread — catch exceptions, `await asyncio.sleep(delay)`, increase delay capped at 30 s, reset on success.
- If `_AIORTSP_AVAILABLE` is False, `__init__` raises `ImportError` with pip install instructions.

---

### Phase F — `siyi_sdk/stream/stream.py`

```python
"""SIYIStream — the public async streaming API."""
from __future__ import annotations
import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable

import structlog

from .base import AbstractStreamBackend
from .models import StreamBackend, StreamConfig, StreamFrame

_log = structlog.get_logger(__name__)

class SIYIStream:
    """Async RTSP video stream receiver for SIYI cameras.

    Delivers decoded frames to registered async callbacks. Handles reconnection
    transparently. Thread-safe for callback registration.

    Example:
        stream = SIYIStream(StreamConfig(rtsp_url="rtsp://192.168.144.25:8554/video1"))

        @stream.on_frame
        async def handle(frame: StreamFrame) -> None:
            cv2.imshow("live", frame.frame)
            cv2.waitKey(1)

        await stream.start()
        await asyncio.sleep(60)
        await stream.stop()
    """

    def __init__(self, config: StreamConfig) -> None: ...

    def _select_backend(self) -> AbstractStreamBackend:
        """Auto-probe: GStreamer → aiortsp → OpenCV."""
        ...

    async def start(self) -> None:
        """Begin streaming. Idempotent — safe to call if already running."""

    async def stop(self) -> None:
        """Stop streaming and release resources. Idempotent."""

    def on_frame(
        self,
        callback: Callable[[StreamFrame], Awaitable[None]] | Callable[[StreamFrame], None],
    ) -> Callable[[], None]:
        """Register a frame callback. Returns an unsubscribe callable.

        The callback may be sync or async. Sync callbacks are called directly;
        async callbacks are scheduled with asyncio.ensure_future.
        """

    def remove_frame_callback(
        self,
        callback: Callable[[StreamFrame], Awaitable[None]] | Callable[[StreamFrame], None],
    ) -> None: ...

    @property
    def is_running(self) -> bool: ...

    @property
    def fps(self) -> float:
        """Rolling 1-second frame rate."""

    @property
    def last_frame(self) -> StreamFrame | None:
        """Most recently decoded frame; None if no frame received yet."""
```

Implementation notes:
- `on_frame` may also be used as a decorator (return value is the unsubscribe callable).
- Internal frame loop: `async for frame in backend.frame_generator(): dispatch(frame); update fps counter`.
- FPS counter: keep a `deque` of `time.monotonic()` timestamps, prune entries older than 1 s, `fps = len(deque)`.
- `_dispatch(frame)`: call each registered callback; if it's a coroutine function use `asyncio.ensure_future`; catch and log exceptions per-callback so one bad callback never kills the loop.
- Auto-backend selection order: try `GStreamerBackend` (import check) → try `AiortspBackend` → fall back to `OpenCVBackend`. If none available, raise `ImportError` listing what to install.

---

### Phase G — `siyi_sdk/stream/__init__.py`

```python
"""SIYI camera RTSP video streaming."""
from .models import (
    CameraGeneration,
    CAMERA_GENERATION_MAP,
    StreamBackend,
    StreamConfig,
    StreamFrame,
    build_rtsp_url,
)
from .stream import SIYIStream

__all__ = [
    "CameraGeneration",
    "CAMERA_GENERATION_MAP",
    "StreamBackend",
    "StreamConfig",
    "StreamFrame",
    "SIYIStream",
    "build_rtsp_url",
]
```

Then update `siyi_sdk/__init__.py` — add all stream exports to `__all__` and import them.

---

### Phase H — `SIYIClient.create_stream()` in `siyi_sdk/client.py`

Add ONE method to `SIYIClient`. Do not change any existing logic:

```python
def create_stream(
    self,
    stream: Literal["main", "sub"] = "main",
    generation: CameraGeneration = CameraGeneration.NEW,
    backend: StreamBackend = StreamBackend.AUTO,
    **kwargs: object,
) -> "SIYIStream":
    """Create an RTSP stream connected to this camera's IP address.

    Args:
        stream: "main" for primary high-resolution stream,
                "sub" for secondary low-resolution stream (new-gen only).
        generation: CameraGeneration.NEW for ZT30/ZT6+,
                    CameraGeneration.OLD for ZR30/ZR10/A8Mini/A2Mini/R1M.
        backend: Backend to use; AUTO probes GStreamer → aiortsp → OpenCV.
        **kwargs: Forwarded to StreamConfig (e.g. latency_ms, reconnect_delay).

    Returns:
        A SIYIStream instance (not yet started — call await stream.start()).
    """
    from siyi_sdk.stream import SIYIStream, StreamConfig, build_rtsp_url
    url = build_rtsp_url(host=self._host, stream=stream, generation=generation)
    return SIYIStream(StreamConfig(rtsp_url=url, backend=backend, **kwargs))
```

Add the required `CameraGeneration` and `StreamBackend` imports to `client.py`'s import section.

**Important**: `self._host` is the IP address string stored during `__init__`. Read the existing `client.py` to find the exact attribute name and use it.

---

### Phase I — `pyproject.toml` updates

Add these optional dependency groups:

```toml
[project.optional-dependencies]
stream         = ["opencv-python>=4.5"]
stream-opencv  = ["opencv-python>=4.5"]
stream-gst     = ["PyGObject>=3.42"]
stream-aiortsp = ["aiortsp>=1.2", "av>=12.0"]
```

Add `opencv-python>=4.5` to `[tool.hatch.envs.default]` dependencies so tests run with OpenCV available.

Add mypy overrides for optional third-party modules:

```toml
[[tool.mypy.overrides]]
module = ["cv2", "gi.*", "gi.repository.*", "aiortsp.*", "av.*"]
ignore_missing_imports = true
```

---

### Phase J — Tests (`tests/stream/`)

Create `tests/stream/__init__.py` (empty).

#### `tests/stream/conftest.py`

```python
import asyncio
import numpy as np
import pytest
from siyi_sdk.stream.models import StreamConfig, StreamFrame, StreamBackend
from siyi_sdk.stream.base import AbstractStreamBackend

class MockStreamBackend(AbstractStreamBackend):
    """Yields a fixed list of frames then stops."""
    BACKEND_NAME = "mock"

    def __init__(self, config: StreamConfig, frames: list[StreamFrame]) -> None:
        super().__init__(config)
        self._frames = frames
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    def frame_available(self) -> bool:
        return bool(self._frames)

    def read_frame_nowait(self) -> StreamFrame | None:
        return self._frames[0] if self._frames else None

    async def frame_generator(self):
        for frame in self._frames:
            await asyncio.sleep(0)
            yield frame

@pytest.fixture
def sample_frame() -> StreamFrame:
    return StreamFrame(
        frame=np.zeros((720, 1280, 3), dtype=np.uint8),
        timestamp=0.0,
        width=1280,
        height=720,
        backend="mock",
    )

@pytest.fixture
def stream_config() -> StreamConfig:
    return StreamConfig(rtsp_url="rtsp://192.168.144.25:8554/video1")
```

#### `tests/stream/test_models.py`

Required tests:
- `build_rtsp_url` for all combinations: (old/new) × (main/sub) × custom host.
- `build_rtsp_url(generation=OLD, stream="sub")` returns the `main.264` URL (sub ignored for old-gen).
- `CameraGeneration` members are correct.
- `CAMERA_GENERATION_MAP` contains all expected models.
- `StreamConfig` default values are correct.
- `StreamConfig` with invalid `latency_ms=-1` raises `ValueError`.
- `StreamConfig` with invalid `reconnect_delay=0` raises `ValueError`.
- `StreamConfig` with invalid `buffer_size=0` raises `ValueError`.
- `StreamFrame` stores numpy array reference correctly.

#### `tests/stream/test_stream.py`

Required tests (all use `MockStreamBackend`, injected via monkeypatch of `SIYIStream._select_backend`):
- `start()` transitions `is_running` False → True.
- `stop()` transitions `is_running` True → False.
- `start()` is idempotent (second call is a no-op).
- `stop()` is idempotent (no error if already stopped).
- `on_frame` callback receives every frame from the mock backend.
- Async callbacks are awaited correctly.
- Sync callbacks are called directly.
- `remove_frame_callback` stops future deliveries.
- `on_frame` used as decorator returns an unsubscribe callable; calling it stops delivery.
- Bad callback (raises exception) does not kill the stream loop; remaining callbacks still fire.
- `last_frame` is `None` before any frame, then holds the most recent frame.
- `fps` is 0.0 before frames arrive; updates correctly after frames.
- Multiple callbacks registered — all receive each frame.
- `on_frame` decorator form: `@stream.on_frame async def handler(f): ...` works.

#### `tests/stream/test_opencv_backend.py`

Required tests:
- Skip entire module if `cv2` is not importable: `pytest.importorskip("cv2")`.
- `OpenCVBackend(config)` raises `ImportError` if cv2 not available (test with monkeypatch).
- `StreamConfig` flows into backend correctly (url, buffer_size).
- `build_rtsp_url` produces the URL that backend would use.
- Mock `cv2.VideoCapture` to verify `CAP_PROP_BUFFERSIZE` is set to `config.buffer_size`.
- Mock `cap.read()` to return a fake BGR frame; verify `StreamFrame` is created correctly.
- Verify thread is daemon.
- `disconnect()` stops the thread within 5 s.

#### `tests/stream/test_gstreamer_backend.py`

Required tests:
- Skip entire module if `gi` is not importable: `pytest.importorskip("gi")`.
- `GStreamerBackend(config)` raises `ImportError` if gi not available.
- Pipeline string contains correct RTSP URL.
- Pipeline string uses `tcp` protocol when `config.transport == "tcp"`.
- Pipeline string uses correct latency value from `config.latency_ms`.
- H.265 pipeline template is used when codec is `h265`.

#### `tests/stream/test_aiortsp_backend.py`

Required tests:
- Skip entire module if `aiortsp` is not importable: `pytest.importorskip("aiortsp")`.
- `AiortspBackend(config)` raises `ImportError` if aiortsp/av not available.
- Verify `StreamConfig.rtsp_url` is passed to the RTSP connection.

#### Integration test (hardware-gated)

Add `tests/stream/test_hil_stream.py`:

```python
"""Hardware-in-the-loop test — skipped unless SIYI_HIL=1 and camera reachable."""
import os
import pytest
from siyi_sdk.stream import SIYIStream, StreamConfig, build_rtsp_url, CameraGeneration

@pytest.mark.hil
@pytest.mark.skipif(os.environ.get("SIYI_HIL") != "1", reason="HIL gate: set SIYI_HIL=1")
async def test_rtsp_receives_frames_opencv():
    import cv2
    config = StreamConfig(
        rtsp_url=build_rtsp_url(generation=CameraGeneration.NEW),
        backend="opencv",
    )
    stream = SIYIStream(config)
    frames = []
    stream.on_frame(lambda f: frames.append(f))
    await stream.start()
    import asyncio
    await asyncio.sleep(3)
    await stream.stop()
    assert len(frames) > 0, "Expected at least one frame in 3 seconds"
    assert stream.fps > 0
```

---

### Phase K — Examples (`examples/`)

Write six runnable example scripts. Each must:
- Have a module-level docstring explaining what camera model it targets and what it demonstrates.
- Import only from `siyi_sdk` (no internal modules).
- Be self-contained with `asyncio.run(main())` at the bottom under `if __name__ == "__main__":`.
- Gracefully handle `KeyboardInterrupt`.
- Not require a live camera to import (only to run).

**`examples/rtsp_opencv_new_gen.py`** — New-gen camera (ZT30/ZT6), OpenCV backend, display with cv2.imshow.

**`examples/rtsp_opencv_old_gen.py`** — Old-gen camera (ZR10/A8Mini/ZR30/A2Mini), OpenCV, uses `/main.264` URL. Note in docstring that only one stream is available.

**`examples/rtsp_gstreamer.py`** — New-gen camera, GStreamer backend, print fps every second. Includes the pipeline string it will use as a comment.

**`examples/rtsp_sub_stream.py`** — New-gen camera, OpenCV, sub stream (`/video2`). Note in docstring that sub stream is new-gen only.

**`examples/rtsp_record.py`** — New-gen camera, OpenCV, save 30 seconds of video to `output.mp4` using `cv2.VideoWriter`. Print progress.

**`examples/rtsp_with_control.py`** — Simultaneously connect `SIYIClient` (gimbal control) and start an RTSP stream using `client.create_stream()`. Subscribe attitude stream. Print attitude + fps side-by-side. Demonstrate both channels working concurrently.

---

### Phase L — Documentation Updates

**`docs/streaming.md`** — Create a new comprehensive guide covering:
1. Prerequisites (camera IP, RTSP ports, which URL for which model).
2. Quick-start (5-line example).
3. Backend selection guide (table: latency, deps, when to use each).
4. Old-gen vs new-gen camera URL differences.
5. `StreamConfig` reference (all fields with defaults and explanation).
6. Reconnection behaviour.
7. Using `SIYIClient.create_stream()` vs standalone `SIYIStream`.
8. GStreamer system package installation commands.
9. Latency tuning tips.
10. SIYI FPV private protocol (documented, not implemented).

**`README.md`** — Add a "Video Streaming" section after the existing quick-start section. 10–20 lines maximum. Link to `docs/streaming.md` for details.

**`CHANGELOG.md`** — Add an `## [Unreleased]` section (or update if one exists) with:
```markdown
### Added
- `siyi_sdk.stream` sub-package: RTSP video streaming with OpenCV, GStreamer, and aiortsp+PyAV backends
- `SIYIStream` async class with callback-based frame delivery and auto-reconnect
- `build_rtsp_url()` helper covering old-gen (`/main.264`) and new-gen (`/video1`, `/video2`) cameras
- `CameraGeneration` enum and `CAMERA_GENERATION_MAP` lookup
- `SIYIClient.create_stream()` convenience factory
- Six runnable examples in `examples/`
- `docs/streaming.md` streaming guide
```

---

### Coding Standards (same as rest of package)

- Python 3.10+, `from __future__ import annotations` in every file.
- Full type annotations on every function and method.
- `mypy --strict` — zero errors. Add `ignore_missing_imports = true` for cv2/gi/aiortsp/av.
- `ruff check` + `ruff format` + `black` — zero violations.
- 100-character line length.
- Google-style docstrings on every public class, method, and function.
- No bare `except` clauses — always catch specific exceptions.
- No magic numbers — define constants in `stream/models.py` (e.g. `_RECONNECT_DELAY_CAP = 30.0`).
- No comments explaining WHAT the code does — only WHY when non-obvious.

### Logging Requirements

Use `structlog.get_logger(__name__)` in every module.

- `DEBUG`: every frame decoded (include backend name, width, height, timestamp).
- `INFO`: stream started, stream stopped, backend selected, reconnect succeeded.
- `WARNING`: frame dropped (queue full), reconnect attempt (include attempt number and delay).
- `ERROR`: unrecoverable connect failure, backend crash, callback exception.

---

### Acceptance Criteria

Before declaring done, verify ALL of these pass:

1. `hatch run lint:lint` — zero violations.
2. `hatch run lint:typecheck` — zero mypy errors.
3. `pytest tests/ --cov=siyi_sdk --cov-fail-under=90 -v` — all green, coverage ≥ 90%.
4. `pytest tests/stream/ -v` — all stream tests green (hardware-gated tests auto-skipped).
5. `pytest -m "not hil"` — zero failures, zero errors.
6. All six example scripts are importable without a live camera: `python -c "import examples.rtsp_opencv_new_gen"` (adjust for actual import path).
7. `docs/streaming.md` exists and covers all 10 topics listed above.
8. `README.md` has a Video Streaming section.
9. `CHANGELOG.md` updated.

---

### Done Report

After completing all work, output a DONE REPORT in this exact format:

```
DONE REPORT — siyi-sdk-video-streaming
Files created:    list each with line count
Files modified:   list each with a one-line description of change
Tests added:      N (all passing)
Coverage delta:   +X.X% (overall package coverage before → after)
Decisions made:   any non-obvious choices with justification
Known gaps:       anything intentionally deferred (e.g. aiortsp tests need live camera)
```
