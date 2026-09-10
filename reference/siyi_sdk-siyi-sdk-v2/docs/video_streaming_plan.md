# Video/Camera Streaming Implementation Plan

## Background

The current SIYI SDK handles **gimbal control and camera configuration** via a binary UDP/TCP/Serial protocol.
It does **not** implement video frame streaming. SIYI cameras expose a separate, independent **RTSP server**
on port `8554`, and that is the correct mechanism for receiving live video — completely decoupled from the
control protocol.

This document plans the addition of a `siyi_sdk.stream` sub-package that integrates RTSP video reception
cleanly with the existing async architecture.

---

## SIYI RTSP Endpoints (Per-Model)

SIYI cameras fall into two generations with different RTSP URL schemes. The generation boundary is the
ZT30 — cameras released at ZT30 or later use the **new** addresses; earlier cameras use the **old** scheme.

### New-generation cameras (ZT30, ZT6, and later)

| Stream | RTSP URL |
|--------|----------|
| Main stream | `rtsp://192.168.144.25:8554/video1` |
| Sub stream | `rtsp://192.168.144.25:8554/video2` |

Special case — SIYI AI Camera (ZT30 family):

| Stream | RTSP URL |
|--------|----------|
| AI Camera (A8 Mini context) | `rtsp://192.168.144.60:554/video0` |
| AI Camera (ZR10/ZT30 context) | `rtsp://192.168.144.25:8554/video0` |

### Old-generation cameras (ZR30, ZR10, A8 Mini, A2 Mini, R1M, and earlier)

| Stream | RTSP URL |
|--------|----------|
| Main stream (single stream) | `rtsp://192.168.144.25:8554/main.264` |

> These models expose only one RTSP stream (no separate sub stream via RTSP).
> Sub-stream access on old-gen cameras uses the SIYI FPV private protocol (see below).

### SIYI FPV Private Video Stream Protocol (all models)

A UDP-based private protocol is available on all cameras as an alternative to RTSP.
It is used internally by the SIYI FPV app and may offer lower latency than RTSP on some setups.

| Stream | Address | Port |
|--------|---------|------|
| Camera 1 Main stream | `192.168.144.25` | `37256` |
| Camera 1 Sub stream | `192.168.144.25` | `37255` |
| Camera 2 Main stream | `192.168.144.26` | `37256` |
| Camera 2 Sub stream | `192.168.144.26` | `37255` |

> The private protocol format is not publicly documented. This plan focuses on the standard RTSP path.
> The private protocol may be added in a future phase if the packet format is reverse-engineered.

### Summary Table

| Camera Model | Generation | Main RTSP URL | Sub RTSP URL |
|-------------|------------|---------------|--------------|
| ZT6 | New | `rtsp://192.168.144.25:8554/video1` | `rtsp://192.168.144.25:8554/video2` |
| ZT30 | New | `rtsp://192.168.144.25:8554/video1` | `rtsp://192.168.144.25:8554/video2` |
| ZR30 | Old | `rtsp://192.168.144.25:8554/main.264` | — |
| ZR10 | Old | `rtsp://192.168.144.25:8554/main.264` | — |
| A8 Mini | Old | `rtsp://192.168.144.25:8554/main.264` | — |
| A2 Mini | Old | `rtsp://192.168.144.25:8554/main.264` | — |
| R1M | Old | `rtsp://192.168.144.25:8554/main.264` | — |
| AI Camera | New | `rtsp://192.168.144.60:554/video0` | — |

### IP Addresses Reference

| Device | IP Address |
|--------|-----------|
| Air Unit | `192.168.144.11` |
| Ground Unit | `192.168.144.12` |
| Handheld Ground Station (Android) | `192.168.144.20` |
| Ethernet-to-HDMI Converter | `192.168.144.50` |
| AI Camera | `192.168.144.60` |
| Optical Pod / Gimbal Camera (default) | `192.168.144.25` |
| IP67 Camera A | `192.168.144.25` |
| IP67 Camera B | `192.168.144.26` |

The stream is entirely independent of the control channel. `SIYIClient` can still be used in parallel
to adjust encoding, stitching mode, or gimbal attitude while the RTSP stream runs.

---

## Design Goals

1. **Async-native** — `SIYIStream` is an `asyncio`-compatible class; no hidden blocking calls on the event loop.
2. **Clean separation** — streaming lives in `siyi_sdk/stream/` and does not pollute `client.py`.
3. **Backend-agnostic** — the public API is the same regardless of whether OpenCV, GStreamer, or PyAV
   is used underneath. Backends are selected at construction time.
4. **Low latency** — sensible defaults minimize pipeline buffering.
5. **Robust reconnection** — the stream auto-reconnects on network drops with configurable back-off.
6. **Callback-based frames** — frames are delivered to callers via registered async callbacks, mirroring the
   existing `on_attitude` / `on_laser_distance` pattern in `SIYIClient`.
7. **Optional dependency** — heavy libraries (GStreamer, PyAV) are optional extras; OpenCV+threading
   is the zero-extra-dependency fallback.

---

## Library Comparison and Selection

| Backend | Latency | Async-native | HW accel | Dependencies | Verdict |
|---------|---------|--------------|----------|-------------|---------|
| OpenCV + `threading` | Medium (~300–500 ms) | No (thread bridge) | No | `opencv-python` | **Default fallback** — simplest, works everywhere |
| GStreamer + `appsink` | Low (~100–220 ms) | No (thread bridge) | Yes (VA-API, NVDEC, V4L2) | `gstreamer` system libs + `PyGObject` | **Recommended for production** |
| `aiortsp` + PyAV | Low-medium | Yes | No (software only) | `aiortsp`, `av` | **Best for pure-Python async pipelines** |
| FFmpeg subprocess pipe | Medium | No (pipe bridge) | Optional | `ffmpeg` binary | Useful for re-streaming; not for frame processing |

**Recommended defaults:**
- Default: **GStreamer** when available (lowest latency, hardware acceleration).
- Fallback: **OpenCV** (`cv2.VideoCapture`) via a background daemon thread.
- Pure-async path: **aiortsp + PyAV** for environments without system GStreamer.

---

## Module Layout

```
siyi_sdk/
└── stream/
    ├── __init__.py          # Public exports: SIYIStream, StreamBackend, StreamFrame
    ├── base.py              # Abstract base class AbstractStreamBackend
    ├── models.py            # StreamFrame dataclass, StreamConfig dataclass
    ├── opencv_backend.py    # OpenCV + threading backend
    ├── gstreamer_backend.py # GStreamer + appsink backend (optional)
    ├── aiortsp_backend.py   # aiortsp + PyAV backend (optional)
    └── stream.py            # SIYIStream — the public async API
```

### Key Public Types

```python
class CameraGeneration(str, Enum):
    """RTSP URL scheme generation."""
    OLD = "old"   # ZR30, ZR10, A8 Mini, A2 Mini, R1M → /main.264, single stream
    NEW = "new"   # ZT30, ZT6 and later → /video1 (main), /video2 (sub)

# Maps known model strings to their generation
CAMERA_GENERATION: dict[str, CameraGeneration] = {
    "zt30": CameraGeneration.NEW,
    "zt6":  CameraGeneration.NEW,
    "zr30": CameraGeneration.OLD,
    "zr10": CameraGeneration.OLD,
    "a8":   CameraGeneration.OLD,
    "a2":   CameraGeneration.OLD,
    "r1m":  CameraGeneration.OLD,
}

@dataclass
class StreamConfig:
    rtsp_url: str                       # Full RTSP URL (use build_rtsp_url() helpers)
    backend: StreamBackend              # AUTO, OPENCV, GSTREAMER, AIORTSP
    transport: Literal["tcp", "udp"] = "tcp"  # TCP preferred for stability
    latency_ms: int = 100              # GStreamer rtspsrc latency knob
    reconnect_delay: float = 2.0       # Seconds before reconnect attempt
    max_reconnect_attempts: int = 0    # 0 = unlimited
    buffer_size: int = 1               # OpenCV CAP_PROP_BUFFERSIZE

# Convenience constructors — avoids hard-coding URL strings in user code
def build_rtsp_url(
    host: str = "192.168.144.25",
    stream: Literal["main", "sub"] = "main",
    generation: CameraGeneration = CameraGeneration.NEW,
) -> str:
    """Return the correct RTSP URL for the given host, stream, and camera generation.

    Old-gen (ZR30/ZR10/A8Mini/A2Mini): rtsp://<host>:8554/main.264  (main only)
    New-gen (ZT30/ZT6+):               rtsp://<host>:8554/video1  (main)
                                        rtsp://<host>:8554/video2  (sub)
    """
    if generation == CameraGeneration.OLD:
        return f"rtsp://{host}:8554/main.264"
    path = "video1" if stream == "main" else "video2"
    return f"rtsp://{host}:8554/{path}"

@dataclass
class StreamFrame:
    frame: np.ndarray                  # BGR frame (H x W x 3)
    timestamp: float                   # monotonic time of capture
    width: int
    height: int
    backend: str                       # Which backend produced it

class StreamBackend(str, Enum):
    AUTO = "auto"
    OPENCV = "opencv"
    GSTREAMER = "gstreamer"
    AIORTSP = "aiortsp"
```

### SIYIStream Public API

```python
class SIYIStream:
    def __init__(self, config: StreamConfig) -> None: ...

    async def start(self) -> None:
        """Begin streaming; connect to the RTSP endpoint."""

    async def stop(self) -> None:
        """Stop streaming and release resources."""

    def on_frame(self, callback: Callable[[StreamFrame], Awaitable[None]]) -> None:
        """Register an async callback invoked for every decoded frame."""

    def remove_frame_callback(self, callback) -> None: ...

    @property
    def is_running(self) -> bool: ...

    @property
    def fps(self) -> float:
        """Measured frame rate over the last second."""

    @property
    def last_frame(self) -> StreamFrame | None:
        """The most recently decoded frame (non-blocking peek)."""
```

`SIYIStream` owns an internal `asyncio.Task` that runs the chosen backend in a daemon thread
(OpenCV / GStreamer) or coroutine (aiortsp), dispatching frames to registered callbacks via
`asyncio.get_event_loop().call_soon_threadsafe`.

---

## Backend Implementation Details

### OpenCV Backend

```
cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
  CAP_PROP_BUFFERSIZE=1   → drop stale frames
  OPENCV_FFMPEG_CAPTURE_OPTIONS: rtsp_transport=tcp  → force TCP
```

- Runs in a `threading.Thread(daemon=True)`.
- Thread calls `cap.read()` in a tight loop; on failure closes and re-opens after `reconnect_delay`.
- Newest frame only is kept in a `threading.Event` + `deque(maxlen=1)` to avoid memory growth.
- Thread posts frames to the asyncio loop via `loop.call_soon_threadsafe(dispatch_frame, frame)`.

### GStreamer Backend

Pipeline template (H.264 — auto-selected based on `EncodingParams.enc_type`):

```
rtspsrc location={url} protocols={transport} latency={latency_ms} buffer-mode=slave
  ! queue max-size-buffers=1 leaky=downstream
  ! rtph264depay
  ! h264parse
  ! decodebin   ← auto-selects HW decoder if available (vah264dec, nvv4l2decoder, avdec_h264)
  ! videoconvert
  ! video/x-raw,format=BGR
  ! appsink name=sink emit-signals=True max-buffers=1 drop=True
```

For H.265, replace `rtph264depay ! h264parse` with `rtph265depay ! h265parse`.

- `appsink`'s `new-sample` signal is connected to a Python callback.
- GStreamer's own main loop runs in a background thread via `GLib.MainLoop`.
- Frames extracted from `Gst.Sample` → `numpy` array and dispatched to asyncio.
- Bus error/EOS messages trigger reconnection.

### aiortsp + PyAV Backend

- Opens an `aiortsp.RTSPConnection` (pure-Python RTSP client, no system libs).
- Reads RTP packets from the UDP/TCP RTSP session.
- Feeds RTP payloads into a `av.CodecContext` (PyAV wrapping libavcodec) for software decoding.
- Entirely within asyncio; no extra threads needed.
- Suitable when GStreamer is unavailable (CI, Docker, minimal systems).

---

## Reconnection and Error Handling

```
while running:
    try:
        connect()
        stream_loop()            ← yields frames until error
    except (NetworkError, EOFError, cv2.error):
        log.warning("Stream lost, reconnecting in %ss", delay)
        await asyncio.sleep(delay)
        delay = min(delay * 1.5, 30)   ← exponential back-off, cap 30 s
    else:
        delay = config.reconnect_delay   ← reset on clean stop
```

Unrecoverable errors (auth failure, invalid URL) are raised to the caller immediately.

---

## Integration with SIYIClient

`SIYIStream` is **standalone** — it needs only a `StreamConfig` with the RTSP URL.
However, a convenience factory will be added to `SIYIClient` that knows which URL scheme
to use based on the camera model reported by `get_camera_system_info()` / firmware query:

```python
# In SIYIClient
def create_stream(
    self,
    stream: Literal["main", "sub"] = "main",
    generation: CameraGeneration = CameraGeneration.NEW,
    backend: StreamBackend = StreamBackend.AUTO,
    **kwargs,
) -> SIYIStream:
    """Create an RTSP stream for this camera.

    Pass generation=CameraGeneration.OLD for ZR30, ZR10, A8 Mini, A2 Mini, R1M.
    Pass generation=CameraGeneration.NEW for ZT30, ZT6, and later models.
    Old-gen cameras only support stream="main" (sub stream not available via RTSP).
    """
    url = build_rtsp_url(host=self._host, stream=stream, generation=generation)
    return SIYIStream(StreamConfig(rtsp_url=url, backend=backend, **kwargs))
```

Usage examples:

```python
# New-generation camera (ZT30, ZT6) — main stream
async with await connect_udp("192.168.144.25") as cam:
    stream = cam.create_stream(generation=CameraGeneration.NEW)
    stream.on_frame(my_callback)
    await stream.start()
    await asyncio.sleep(30)
    await stream.stop()

# New-generation camera — sub stream (lower resolution)
stream = cam.create_stream(stream="sub", generation=CameraGeneration.NEW)

# Old-generation camera (ZR10, A8 Mini, ZR30, A2 Mini)
stream = cam.create_stream(generation=CameraGeneration.OLD)
# → uses rtsp://192.168.144.25:8554/main.264

# Explicit URL (any camera)
from siyi_sdk.stream import SIYIStream, StreamConfig
stream = SIYIStream(StreamConfig(rtsp_url="rtsp://192.168.144.25:8554/main.264"))
```

---

## New Optional Dependencies

```toml
# pyproject.toml extras
[project.optional-dependencies]
stream-opencv  = ["opencv-python>=4.5"]
stream-gst     = ["PyGObject>=3.42"]      # GStreamer Python bindings
stream-aiortsp = ["aiortsp>=1.2", "av>=12.0"]  # aiortsp + PyAV
stream         = ["opencv-python>=4.5"]   # Default stream extra (OpenCV)
```

System-level prerequisites for GStreamer backend (not pip-installable):
- `gstreamer1.0-plugins-base`
- `gstreamer1.0-plugins-good`
- `gstreamer1.0-plugins-bad` (for H.265)
- `python3-gi` (GObject introspection)

---

## File-by-File Implementation Plan

### Phase A — Models and Base (`stream/models.py`, `stream/base.py`)

1. Define `CameraGeneration` enum (`OLD` / `NEW`) with `CAMERA_GENERATION` lookup dict.
2. Define `build_rtsp_url(host, stream, generation)` helper.
3. Define `StreamFrame` dataclass.
4. Define `StreamConfig` dataclass with sensible defaults.
5. Define `StreamBackend` enum.
6. Define `AbstractStreamBackend` ABC with:
   - `async def connect(self) -> None`
   - `async def disconnect(self) -> None`
   - `def read_frame_nowait(self) -> StreamFrame | None`
   - `async def frame_generator(self) -> AsyncIterator[StreamFrame]`

### Phase B — OpenCV Backend (`stream/opencv_backend.py`)

1. Implement `OpenCVBackend(AbstractStreamBackend)`.
2. Background thread with `cap.read()` loop.
3. Thread-safe frame queue (`deque(maxlen=1)`).
4. Reconnection with back-off inside thread.
5. Expose async `frame_generator` via `asyncio.Queue`.

### Phase C — GStreamer Backend (`stream/gstreamer_backend.py`)

1. Implement `GStreamerBackend(AbstractStreamBackend)` guarded by `try: import gi`.
2. Build pipeline string based on `StreamConfig` (H.264 vs H.265, TCP vs UDP, latency).
3. Wire `appsink` `new-sample` signal → numpy conversion → asyncio dispatch.
4. Handle bus `ERROR` / `EOS` for reconnection.
5. `GLib.MainLoop` in a daemon thread.

### Phase D — aiortsp Backend (`stream/aiortsp_backend.py`)

1. Implement `AiortspBackend(AbstractStreamBackend)` guarded by `try: import aiortsp, av`.
2. Open RTSP session, negotiate H.264/H.265 RTP track.
3. Async generator yielding `StreamFrame` objects.
4. Reconnection logic with asyncio back-off.

### Phase E — SIYIStream (`stream/stream.py`)

1. Implement `SIYIStream` with auto-backend selection (`AUTO` → probe GStreamer → probe aiortsp → OpenCV).
2. `start()` creates asyncio task running the frame loop.
3. Frame loop calls `frame_generator()` from backend, dispatches to callbacks.
4. `stop()` cancels the task and calls `backend.disconnect()`.
5. Expose `fps`, `last_frame`, `is_running` properties.

### Phase F — Factory in SIYIClient (`client.py`)

1. Add `create_stream()` convenience method.
2. Derive RTSP URL from `self._host`.
3. Document in docstring.

### Phase G — Public Exports (`stream/__init__.py`, `siyi_sdk/__init__.py`)

1. Export `SIYIStream`, `StreamConfig`, `StreamFrame`, `StreamBackend`, `CameraGeneration`, `build_rtsp_url`.
2. Add to top-level `siyi_sdk.__all__`.

### Phase H — Examples (`examples/`)

1. `examples/rtsp_opencv_new_gen.py` — ZT30/ZT6 main stream with OpenCV (new-gen URL).
2. `examples/rtsp_opencv_old_gen.py` — ZR10/A8Mini with OpenCV (old-gen URL `/main.264`).
3. `examples/rtsp_gstreamer.py` — GStreamer low-latency pipeline (new-gen).
4. `examples/rtsp_sub_stream.py` — new-gen sub stream (`/video2`) for low-bandwidth use.
5. `examples/rtsp_record.py` — save stream to MP4 via OpenCV `VideoWriter`.
6. `examples/rtsp_with_control.py` — simultaneous gimbal control + video stream.

### Phase I — Tests (`tests/stream/`)

1. Unit tests for `StreamConfig` validation.
2. Unit tests for `StreamFrame` construction.
3. Mock backend tests for `SIYIStream` callback dispatch.
4. Integration test skeleton (skipped unless `SIYI_RTSP_URL` env var set).

### Phase J — Documentation

1. Update `README.md` — add "Video Streaming" section with quick-start.
2. Add `docs/streaming.md` — full streaming guide (backends, GStreamer pipelines, latency tuning).
3. Update `CHANGELOG.md` with feature entry.

---

## Latency Budget (Expected)

| Backend | Connection overhead | Decode latency | Typical end-to-end |
|---------|--------------------|-----------------|--------------------|
| GStreamer (HW decode) | ~50 ms | ~30–50 ms | **~100–220 ms** |
| GStreamer (SW decode) | ~50 ms | ~80–120 ms | **~150–300 ms** |
| OpenCV / FFmpeg | ~100 ms | ~150–250 ms | **~300–500 ms** |
| aiortsp + PyAV | ~80 ms | ~100–200 ms | **~200–400 ms** |

Primary latency knobs:
- `StreamConfig.latency_ms` (GStreamer `rtspsrc latency=` parameter)
- `StreamConfig.buffer_size` (OpenCV `CAP_PROP_BUFFERSIZE`)
- `queue max-size-buffers=1 leaky=downstream` (GStreamer — drop stale frames)

---

## Open Questions / Future Work

- **Multi-stream**: SIYI cameras expose main (high-res) and sub (low-res) streams. Plan for
  dual-stream support (e.g., `StreamType.MAIN` / `StreamType.SUB`).
- **HDMI/CVBS**: For applications needing HDMI output, the existing `capture(ENABLE_HDMI)` command
  activates the HDMI port — document this workflow separately.
- **Frame timestamping**: Investigate whether RTSP/RTP `Timestamp` fields can be surfaced for
  accurate sensor-fusion timestamps.
- **ROS 2 bridge**: A thin `rclpy` wrapper over `SIYIStream` for robotics workflows.
- **Authentication**: SIYI cameras currently do not require RTSP credentials, but the URL format
  should support `rtsp://user:pass@host:8554/live` for future-proofing.
