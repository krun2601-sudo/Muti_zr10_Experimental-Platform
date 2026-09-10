# SIYI Camera RTSP Video Streaming

The `siyi_sdk.stream` sub-package provides RTSP video reception from SIYI
cameras. It is completely decoupled from the control channel (`SIYIClient`):
video reception does not require a UDP/TCP connection to the camera, only
network access to port 8554 on the camera IP.

---

## 1. Prerequisites

- Camera must be reachable at its IP address (default: `192.168.144.25`).
- RTSP server is always running on the camera; no command is required to start it.
- Port `8554` must be accessible from the host running the Python code.
- At least one Python streaming backend must be installed (see section 3).

### Camera IP Address Reference

| Device | IP |
|--------|-----|
| Gimbal Camera / Optical Pod (default) | `192.168.144.25` |
| IP67 Camera B | `192.168.144.26` |
| AI Camera (ZT30 family) | `192.168.144.60` |

---

## 2. Quick Start

```python
import asyncio
from siyi_sdk import SIYIStream, StreamConfig, build_rtsp_url, CameraGeneration

async def main() -> None:
    stream = SIYIStream(StreamConfig(
        rtsp_url=build_rtsp_url(generation=CameraGeneration.NEW)
    ))

    @stream.on_frame
    async def handle(frame):
        print(f"Frame {frame.width}x{frame.height} at {frame.timestamp:.3f}")

    await stream.start()
    await asyncio.sleep(10)
    await stream.stop()

asyncio.run(main())
```

---

## 3. Backend Selection Guide

Three streaming backends are available. `AUTO` (the default) probes them in
the order shown below.

| Backend | Latency | Dependencies | When to Use |
|---------|---------|-------------|-------------|
| **GStreamer** | ~100–220 ms | `PyGObject`, system GStreamer | Production; supports HW decode |
| **aiortsp + PyAV** | ~200–400 ms | `aiortsp`, `av` | Pure-Python async; no system libs |
| **OpenCV** | ~300–500 ms | `opencv-python` | Simplest; works everywhere |

Install a backend using pip extras (recommended):

```bash
# OpenCV — simplest, no system deps required
pip install "siyi-sdk[stream-opencv]"

# aiortsp + PyAV — pure-Python, no system deps required
pip install "siyi-sdk[stream-aiortsp]"

# GStreamer — lowest latency, but requires system packages first (see section 8)
pip install "siyi-sdk[stream-gst]"
```

Or install the backends directly without the package extras:

```bash
# OpenCV
pip install opencv-python

# aiortsp + PyAV
pip install aiortsp av

# GStreamer (Ubuntu/Debian) — system packages CANNOT be installed via pip
sudo apt install gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
     gstreamer1.0-libav python3-gi python3-gst-1.0
pip install PyGObject
```

> **Note:** GStreamer requires system-level packages (`apt`/`brew`) that pip cannot
> install. See [section 8](#8-gstreamer-system-package-installation) for full platform
> instructions.

---

## 4. Old-Gen vs New-Gen Camera URL Differences

SIYI cameras are divided into two generations based on the ZT30 release.

| Generation | Models | RTSP Main URL | RTSP Sub URL |
|-----------|--------|--------------|-------------|
| **New** | ZT30, ZT6 | `rtsp://<host>:8554/video1` | `rtsp://<host>:8554/video2` |
| **Old** | ZR30, ZR10, A8 Mini, A2 Mini, R1M | `rtsp://<host>:8554/main.264` | — (not via RTSP) |

Use `build_rtsp_url()` to avoid hardcoding URLs:

```python
from siyi_sdk import build_rtsp_url, CameraGeneration

# New-gen main stream
url = build_rtsp_url(generation=CameraGeneration.NEW, stream="main")
# → rtsp://192.168.144.25:8554/video1

# New-gen sub stream
url = build_rtsp_url(generation=CameraGeneration.NEW, stream="sub")
# → rtsp://192.168.144.25:8554/video2

# Old-gen (sub argument is ignored)
url = build_rtsp_url(generation=CameraGeneration.OLD)
# → rtsp://192.168.144.25:8554/main.264
```

---

## 5. StreamConfig Reference

```python
@dataclass
class StreamConfig:
    rtsp_url: str                         # Full RTSP URL (required)
    backend: StreamBackend = AUTO         # Backend selection
    transport: Literal["tcp","udp"] = "tcp"  # TCP recommended for stability
    latency_ms: int = 100                 # GStreamer rtspsrc latency
    reconnect_delay: float = 2.0          # Initial back-off seconds
    max_reconnect_attempts: int = 0       # 0 = unlimited
    buffer_size: int = 1                  # OpenCV CAP_PROP_BUFFERSIZE
```

All fields are validated on construction:
- `latency_ms >= 0`
- `reconnect_delay > 0`
- `buffer_size >= 1`

---

## 6. Reconnection Behaviour

All backends reconnect automatically after a stream failure using exponential
back-off:

```
initial delay = reconnect_delay (default 2.0 s)
on each failure: delay = min(delay × 1.5, 30.0)
on success: delay reset to reconnect_delay
```

To limit attempts, set `max_reconnect_attempts` (0 = unlimited):

```python
config = StreamConfig(
    rtsp_url="...",
    reconnect_delay=3.0,
    max_reconnect_attempts=5,
)
```

---

## 7. SIYIClient.create_stream() vs Standalone SIYIStream

Both approaches work identically at runtime. `create_stream()` is a convenience
method that automatically derives the RTSP URL from the camera IP already
stored in the connected client:

```python
# Standalone (explicit URL)
from siyi_sdk import SIYIStream, StreamConfig
stream = SIYIStream(StreamConfig(rtsp_url="rtsp://192.168.144.25:8554/video1"))

# Via connected SIYIClient (URL derived from client's IP)
stream = client.create_stream(stream="main", generation=CameraGeneration.NEW)
```

Both return a `SIYIStream` that must be started with `await stream.start()`.

---

## 8. GStreamer System Package Installation

### Ubuntu / Debian

You can use the provided convenience script to install all required dependencies:

```bash
chmod +x install_gst_dependencies.sh
./install_gst_dependencies.sh
```

Or manually install them. Note that `build-essential`, `pkg-config`, `libcairo2-dev`, `libgirepository1.0-dev`, `libgirepository-2.0-dev` and `python3-dev` are required because `pip` often needs to compile `PyGObject` and `pycairo` from source:

```bash
sudo apt update
sudo apt install \
    build-essential \
    pkg-config \
    libcairo2-dev \
    libgirepository1.0-dev \
    libgirepository-2.0-dev \
    python3-dev \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-libav \
    python3-gi \
    python3-gst-1.0 \
    gir1.2-gst-plugins-base-1.0 \
    gir1.2-gstreamer-1.0
pip install PyGObject
```

### macOS (Homebrew)

```bash
brew install gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad pygobject3
```

---

## 9. Latency Tuning Tips

Lower latency requires reducing pipeline buffering at each stage:

- **GStreamer**: Reduce `latency_ms` (minimum ~20 ms before frame drops appear).
  The `queue max-size-buffers=1 leaky=downstream` in the default pipeline already
  drops stale frames automatically.
- **OpenCV**: Set `buffer_size=1` (the default) so OpenCV's FFmpeg wrapper does
  not buffer stale frames.
- **RTSP transport**: Use `transport="tcp"` (default) for reliable ordered delivery.
  `transport="udp"` reduces RTT but can cause H.264 decode errors on packet loss.
- **Network**: Use a wired or 5 GHz Wi-Fi connection. 2.4 GHz Wi-Fi adds 20–80 ms
  of additional jitter.

---

## 10. SIYI FPV Private Protocol

SIYI cameras also expose a private UDP-based video protocol used internally by
the SIYI FPV application:

| Stream | Address | Port |
|--------|---------|------|
| Camera 1 Main | `192.168.144.25` | `37256` |
| Camera 1 Sub | `192.168.144.25` | `37255` |
| Camera 2 Main | `192.168.144.26` | `37256` |
| Camera 2 Sub | `192.168.144.26` | `37255` |

The packet format of this protocol is not publicly documented. The `siyi_sdk`
package uses standard RTSP for all video reception. The private protocol may
be added in a future phase if the packet format is reverse-engineered.
