"""有界异步 CSV 日志：控制循环只入队，后台线程负责磁盘写入。

必需实验数据不静默丢弃。队列满/磁盘错误直接使会话失败并触发设备停机。
每个表以固定 schema 保存，JSON 列承载可扩展字段，未知列会报错。
"""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import queue
import subprocess
import threading
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__

SCHEMAS = {
    "telemetry": ["device_id","sample_t","yaw_deg","pitch_deg","roll_deg","zoom","yaw_rate_dps","pitch_rate_dps","connected","sequence","source","age_s","raw_json"],
    "detections": ["device_id","frame_id","detection_id","capture_t","received_t","time_uncertainty_s","class_id","confidence","x1","y1","x2","y2","width","height"],
    "rays": ["device_id","detection_id","capture_t","ox","oy","oz","dx","dy","dz","angular_std_deg","confidence","class_id","time_uncertainty_s","embedding_json"],
    "localizations": ["localization_id","measurement_t","x_m","y_m","z_m","device_ids_json","detection_ids_json","residual_m","min_angle_deg","condition_number","time_span_s","covariance_json"],
    "tracks": ["track_id","estimate_t","x_m","y_m","z_m","vx_mps","vy_mps","vz_mps","last_seen_t","hits","status","measured","device_ids_json","covariance_json"],
    "actions": ["device_id","issued_t","ttl_s","yaw_deg","pitch_deg","zoom","target_ids_json","reason","parameters_json"],
    "commands": ["device_id","command_t","status","sent","ack","latency_ms","applied_json","error","action_json"],
    "events": ["kind","payload_json"],
    "cycles": ["step","dt_s","work_ms","deadline_miss","detections","rays","localizations","tracks","measured_tracks","metrics_json","diagnostics_json"],
    "truth": ["truth_id","x_m","y_m","z_m"],
    "coverage_cells": ["cell_id","x_m","y_m","z_m","first_covered_t_s","device_ids_json","viewpoint_ids_json","required_views"],
}
SCHEMAS["telemetry_stream"] = list(SCHEMAS["telemetry"])


def jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k):jsonable(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [jsonable(v) for v in value]
    if hasattr(value,"tolist"):
        return jsonable(value.tolist())
    if isinstance(value,float) and (value != value or abs(value) == float("inf")):
        return None
    return value


def dumps(value: Any) -> str:
    return json.dumps(jsonable(value),ensure_ascii=False,separators=(",",":"),allow_nan=False)


def _git_revision() -> str | None:
    try:
        root = Path(__file__).resolve().parent
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root,
                                      stderr=subprocess.DEVNULL, timeout=2, text=True).strip()
        return out or None
    except Exception:
        return None


class CSVRecorder:
    def __init__(self, root: str | Path, config: dict, mode: str, start_t: float = 0.0):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        self.path = Path(root).resolve() / f"{mode}_{stamp}"
        self.path.mkdir(parents=True,exist_ok=False)
        self.mode = mode
        self.run_id = self.path.name
        self.start_t = start_t
        self.created_epoch = time.time()
        self.q: queue.Queue = queue.Queue(maxsize=int(config.get("logging",{}).get("queue_size",30000)))
        self.error: Exception | None = None
        self.counts = {name:0 for name in SCHEMAS}
        self.closed = False
        self._files = {}
        self._writers = {}
        self._metadata_lock = threading.Lock()
        for name, columns in SCHEMAS.items():
            stream = (self.path/f"{name}.csv").open("w",newline="",encoding="utf-8-sig")
            writer = csv.DictWriter(stream,fieldnames=["schema_version","run_id","utc","t_s",*columns])
            writer.writeheader()
            self._files[name],self._writers[name] = stream,writer
        self.metadata = {"schema_version":2,"platform_version":__version__,"mode":mode,
            "run_id":self.run_id,"created_utc":datetime.now(timezone.utc).isoformat(),
            "python":platform.python_version(),"os":platform.platform(),"start_t":start_t,
            "time_basis":"simulation_seconds" if mode=="sim" else "host_monotonic_seconds",
            "config":config,"completed":False,"git_revision":_git_revision()}
        self._write_json("metadata.json",self.metadata)
        self._thread = threading.Thread(target=self._work,name="csv-recorder",daemon=True)
        self._thread.start()

    def _write_json(self,name,value):
        (self.path/name).write_text(json.dumps(jsonable(value),ensure_ascii=False,indent=2),encoding="utf-8")

    def set_metadata(self, **values: Any) -> None:
        """补充会话级可追溯信息；调用频率应低，不在逐周期热路径使用。"""
        if self.closed:
            raise RuntimeError("日志已关闭")
        with self._metadata_lock:
            self.metadata.update(jsonable(values))
            self._write_json("metadata.json", self.metadata)

    def check(self) -> None:
        if self.error:
            raise RuntimeError(f"CSV 日志线程失败: {self.error}") from self.error

    def write(self,table: str,t: float,**values: Any) -> None:
        self.check()
        if self.closed:
            raise RuntimeError("日志已关闭")
        if table not in SCHEMAS or set(values)-set(SCHEMAS[table]):
            raise ValueError(f"日志表或字段不合法: {table}: {set(values)-set(SCHEMAS.get(table,[]))}")
        epoch = self.created_epoch + t-self.start_t
        row = {"schema_version":2,"run_id":self.run_id,
            "utc":datetime.fromtimestamp(epoch,timezone.utc).isoformat(timespec="milliseconds"),
            "t_s":t-self.start_t,**values}
        try:
            self.q.put_nowait((table,row))
        except queue.Full as exc:
            raise RuntimeError("CSV 队列已满，实验中止以避免记录缺失") from exc

    def event(self,kind: str,payload: dict,t: float | None = None):
        if t is None:
            t = time.monotonic() if self.mode!="sim" else self.start_t
        self.write("events",t,kind=kind,payload_json=dumps(payload))

    def _work(self):
        last_flush = time.monotonic()
        try:
            while True:
                item = self.q.get()
                if item is None:
                    self.q.task_done()
                    break
                table,row = item
                self._writers[table].writerow(row)
                self.counts[table] += 1
                self.q.task_done()
                if time.monotonic()-last_flush > .5:
                    for stream in self._files.values():
                        stream.flush()
                    last_flush = time.monotonic()
        except Exception as exc:
            self.error = exc
        finally:
            for stream in self._files.values():
                try:
                    stream.close()
                except Exception as exc:
                    self.error = self.error or exc

    def close(self,completed: bool = True):
        if self.closed:
            return
        self.closed = True
        while self._thread.is_alive():
            try:
                self.q.put(None,timeout=.1)
                break
            except queue.Full:
                self.check()
        self._thread.join(timeout=15)
        if self._thread.is_alive():
            raise RuntimeError("CSV 日志未能在15秒内完成刷新")
        with self._metadata_lock:
            self.metadata.update(completed=bool(completed and not self.error),rows=self.counts,
                                 error=str(self.error) if self.error else "")
            self._write_json("metadata.json",self.metadata)
        manifest = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.path.glob("*.csv")}
        self._write_json("manifest.sha256.json",manifest)
        self.check()
