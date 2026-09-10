from __future__ import annotations

import csv
import json
import platform
import queue
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TELEMETRY_FIELDS = [
    "session_id",
    "timestamp_local",
    "timestamp_utc",
    "elapsed_s",
    "cycle_index",
    "policy_name",
    "policy_phase",
    "policy_diagnostics_json",
    "gimbal_id",
    "gimbal_name",
    "ip",
    "connected",
    "initialized",
    "initial_target_reached",
    "firmware",
    "motion_mode",
    "target_frame",
    "target_azimuth_deg",
    "target_elevation_deg",
    "command_yaw_deg",
    "command_pitch_deg",
    "control_mode",
    "yaw_error_deg",
    "pitch_error_deg",
    "command_yaw_speed",
    "command_pitch_speed",
    "command_was_clamped",
    "command_sequence",
    "command_sent",
    "command_status",
    "ack_received",
    "fallback_used",
    "command_start_elapsed_s",
    "command_complete_elapsed_s",
    "command_batch_offset_ms",
    "command_latency_ms",
    "ack_yaw_deg",
    "ack_pitch_deg",
    "ack_roll_deg",
    "feedback_timestamp_local",
    "feedback_timestamp_utc",
    "feedback_sequence",
    "feedback_source",
    "feedback_age_ms",
    "feedback_stale",
    "actual_azimuth_deg",
    "actual_elevation_deg",
    "actual_yaw_deg",
    "actual_pitch_raw_deg",
    "actual_pitch_deg",
    "actual_roll_deg",
    "yaw_rate_dps",
    "pitch_rate_dps",
    "roll_rate_dps",
    "azimuth_error_deg",
    "elevation_error_deg",
    "ae_error_norm_deg",
    "in_tolerance",
    "command_error_count",
    "consecutive_command_errors",
    "last_error",
]

EVENT_FIELDS = [
    "session_id",
    "timestamp_local",
    "timestamp_utc",
    "elapsed_s",
    "level",
    "event",
    "gimbal_id",
    "message",
    "details_json",
]


class CsvSessionLogger:
    """Non-blocking CSV logger using a dedicated writer thread."""

    def __init__(
        self,
        log_root: str | Path,
        session_name: str,
        queue_size: int = 20000,
        flush_interval_s: float = 0.5,
    ) -> None:
        stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_name)
        self.session_id = f"{safe_name}_{stamp}"
        self.session_dir = Path(log_root).expanduser().resolve() / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=False)

        self._queue: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue(
            maxsize=queue_size
        )
        self._flush_interval_s = flush_interval_s
        self._thread: threading.Thread | None = None
        self._dropped_rows = 0
        self._started = False

    def start(self, config: dict[str, Any], extra_metadata: dict[str, Any] | None = None) -> None:
        metadata = {
            "session_id": self.session_id,
            "created_at_local": datetime.now().astimezone().isoformat(),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python_version": sys.version,
            "config": config,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        with (self.session_dir / "session_metadata.json").open("w", encoding="utf-8") as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2, default=str)

        self._thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._thread.start()
        self._started = True

    def log_telemetry(self, row: dict[str, Any]) -> None:
        self._put("telemetry", row)

    def log_event(self, row: dict[str, Any]) -> None:
        self._put("event", row)

    def _put(self, kind: str, row: dict[str, Any]) -> None:
        if not self._started:
            return
        try:
            self._queue.put_nowait((kind, row))
        except queue.Full:
            self._dropped_rows += 1

    def close(self) -> None:
        if not self._started:
            return
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=5.0)
        self._started = False
        with (self.session_dir / "logger_summary.json").open("w", encoding="utf-8") as file:
            json.dump(
                {"dropped_rows": self._dropped_rows},
                file,
                ensure_ascii=False,
                indent=2,
            )

    def _writer_loop(self) -> None:
        telemetry_path = self.session_dir / "telemetry.csv"
        event_path = self.session_dir / "events.csv"
        with telemetry_path.open("w", newline="", encoding="utf-8-sig") as telemetry_file, event_path.open(
            "w", newline="", encoding="utf-8-sig"
        ) as event_file:
            telemetry_writer = csv.DictWriter(
                telemetry_file,
                fieldnames=TELEMETRY_FIELDS,
                extrasaction="ignore",
            )
            event_writer = csv.DictWriter(
                event_file,
                fieldnames=EVENT_FIELDS,
                extrasaction="ignore",
            )
            telemetry_writer.writeheader()
            event_writer.writeheader()
            last_flush = time.monotonic()

            while True:
                timeout = max(0.05, self._flush_interval_s - (time.monotonic() - last_flush))
                try:
                    item = self._queue.get(timeout=timeout)
                except queue.Empty:
                    item = "flush"

                if item is None:
                    break
                if item != "flush":
                    kind, row = item
                    if kind == "telemetry":
                        telemetry_writer.writerow({field: row.get(field, "") for field in TELEMETRY_FIELDS})
                    else:
                        event_writer.writerow({field: row.get(field, "") for field in EVENT_FIELDS})

                if time.monotonic() - last_flush >= self._flush_interval_s:
                    telemetry_file.flush()
                    event_file.flush()
                    last_flush = time.monotonic()

            telemetry_file.flush()
            event_file.flush()
