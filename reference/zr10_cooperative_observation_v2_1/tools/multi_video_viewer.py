from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import math
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

# OpenCV reads this process-wide option when the FFmpeg captures are opened.
# Set it before importing cv2.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay",
)

import cv2  # type: ignore[import]
import numpy as np

from zr10_coop.config import load_config


@dataclass(slots=True)
class VideoSnapshot:
    frame: np.ndarray | None
    connected: bool
    fps: float
    age_s: float | None
    last_error: str


class LatestFrameReader:
    """Read one RTSP stream in a dedicated thread and retain only the newest frame.

    The reader automatically reconnects when a stream is interrupted. Keeping only
    the newest frame avoids a growing latency caused by old buffered frames.
    """

    def __init__(
        self,
        *,
        name: str,
        ip: str,
        rtsp_url: str,
        reconnect_interval_s: float = 2.0,
    ) -> None:
        self.name = name
        self.ip = ip
        self.rtsp_url = rtsp_url
        self.reconnect_interval_s = reconnect_interval_s

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture: cv2.VideoCapture | None = None

        self._frame: np.ndarray | None = None
        self._frame_time = 0.0
        self._connected = False
        self._last_error = "not started"
        self._fps = 0.0
        self._fps_count = 0
        self._fps_start = time.monotonic()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"video-{self.name}",
            daemon=True,
        )
        self._thread.start()

    def _open_capture(self) -> cv2.VideoCapture:
        capture = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return capture

    def _set_status(self, *, connected: bool, error: str = "") -> None:
        with self._lock:
            self._connected = connected
            if error:
                self._last_error = error
            elif connected:
                self._last_error = ""

    def _store_frame(self, frame: np.ndarray) -> None:
        now = time.monotonic()
        with self._lock:
            self._frame = frame
            self._frame_time = now
            self._connected = True
            self._last_error = ""

            self._fps_count += 1
            elapsed = now - self._fps_start
            if elapsed >= 1.0:
                self._fps = self._fps_count / elapsed
                self._fps_count = 0
                self._fps_start = now

    def _close_capture(self) -> None:
        capture = self._capture
        self._capture = None
        if capture is not None:
            capture.release()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._capture = self._open_capture()
                if not self._capture.isOpened():
                    raise RuntimeError(f"cannot open {self.rtsp_url}")

                self._set_status(connected=True)
                while not self._stop_event.is_set():
                    ok, frame = self._capture.read()
                    if not ok or frame is None:
                        raise RuntimeError("capture.read() failed")
                    self._store_frame(frame)

            except Exception as exc:  # RTSP reconnect boundary
                self._set_status(connected=False, error=str(exc))
                self._close_capture()
                self._stop_event.wait(self.reconnect_interval_s)

        self._close_capture()
        self._set_status(connected=False, error="stopped")

    def snapshot(self) -> VideoSnapshot:
        now = time.monotonic()
        with self._lock:
            frame = None if self._frame is None else self._frame.copy()
            age_s = None if self._frame_time <= 0 else now - self._frame_time
            return VideoSnapshot(
                frame=frame,
                connected=self._connected,
                fps=self._fps,
                age_s=age_s,
                last_error=self._last_error,
            )

    def stop(self) -> None:
        self._stop_event.set()
        self._close_capture()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Display all enabled ZR10 RTSP streams from the project YAML."
    )
    parser.add_argument(
        "--config",
        default="config/three_zr10.yaml",
        help="Project YAML configuration path.",
    )
    parser.add_argument(
        "--transport",
        choices=("tcp", "udp"),
        default="tcp",
        help="RTSP transport. TCP is normally more stable through a switch.",
    )
    parser.add_argument("--tile-width", type=int, default=640)
    parser.add_argument("--tile-height", type=int, default=360)
    parser.add_argument("--columns", type=int, default=2)
    parser.add_argument(
        "--rtsp-port",
        type=int,
        default=8554,
        help="Old-generation ZR10 RTSP port.",
    )
    parser.add_argument(
        "--stream-path",
        default="main.264",
        help="Old-generation ZR10 main stream path.",
    )
    return parser.parse_args()


def letterbox(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize a frame to fit a tile without changing its aspect ratio."""
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    source_h, source_w = frame.shape[:2]
    if source_w <= 0 or source_h <= 0:
        return canvas

    scale = min(width / source_w, height / source_h)
    resized_w = max(1, int(source_w * scale))
    resized_h = max(1, int(source_h * scale))
    resized = cv2.resize(frame, (resized_w, resized_h), interpolation=cv2.INTER_AREA)

    x0 = (width - resized_w) // 2
    y0 = (height - resized_h) // 2
    canvas[y0 : y0 + resized_h, x0 : x0 + resized_w] = resized
    return canvas


def status_tile(
    *,
    reader: LatestFrameReader,
    snapshot: VideoSnapshot,
    width: int,
    height: int,
) -> np.ndarray:
    if snapshot.frame is None:
        tile = np.zeros((height, width, 3), dtype=np.uint8)
        cv2.putText(
            tile,
            "WAITING FOR VIDEO...",
            (30, height // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
    else:
        tile = letterbox(snapshot.frame, width, height)

    age_text = "--" if snapshot.age_s is None else f"{snapshot.age_s:.2f}s"
    connection_text = "ONLINE" if snapshot.connected else "RECONNECTING"
    label = (
        f"{reader.name} | {reader.ip} | {connection_text} | "
        f"FPS {snapshot.fps:.1f} | AGE {age_text}"
    )

    # Draw a dark text background for readability without changing the video data.
    cv2.rectangle(tile, (0, 0), (width, 42), (0, 0, 0), thickness=-1)
    cv2.putText(
        tile,
        label,
        (12, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )

    if not snapshot.connected and snapshot.last_error:
        error_text = snapshot.last_error[:90]
        cv2.rectangle(tile, (0, height - 34), (width, height), (0, 0, 0), thickness=-1)
        cv2.putText(
            tile,
            error_text,
            (12, height - 11),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return tile


def compose_grid(tiles: list[np.ndarray], columns: int) -> np.ndarray:
    if not tiles:
        raise ValueError("No video tiles")
    columns = max(1, columns)
    rows = math.ceil(len(tiles) / columns)
    tile_h, tile_w = tiles[0].shape[:2]
    blank = np.zeros((tile_h, tile_w, 3), dtype=np.uint8)

    padded = tiles + [blank] * (rows * columns - len(tiles))
    row_images = [
        np.hstack(padded[row * columns : (row + 1) * columns])
        for row in range(rows)
    ]
    return np.vstack(row_images)


def main() -> int:
    args = parse_args()

    # The environment variable must reflect the selected transport before any
    # reader opens a VideoCapture object.
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
        f"rtsp_transport;{args.transport}|fflags;nobuffer|flags;low_delay"
    )

    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    devices = config.enabled_gimbals()

    readers = [
        LatestFrameReader(
            name=device.name,
            ip=device.ip,
            rtsp_url=(
                f"rtsp://{device.ip}:{args.rtsp_port}/"
                f"{args.stream_path.lstrip('/')}"
            ),
        )
        for device in devices
    ]

    print("Opening streams:")
    for reader in readers:
        print(f"  {reader.name}: {reader.rtsp_url}")
        reader.start()

    window_name = "ZR10 Cooperative Observation - Multi Video"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    print("Press q or Esc in the video window to exit.")

    try:
        while True:
            tiles = [
                status_tile(
                    reader=reader,
                    snapshot=reader.snapshot(),
                    width=args.tile_width,
                    height=args.tile_height,
                )
                for reader in readers
            ]
            grid = compose_grid(tiles, args.columns)
            cv2.imshow(window_name, grid)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
    except KeyboardInterrupt:
        pass
    finally:
        for reader in readers:
            reader.stop()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
