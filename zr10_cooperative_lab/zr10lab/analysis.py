"""CSV 完整性检查、统计报告和离线重新融合，不访问任何设备。"""
from __future__ import annotations
import csv
import hashlib
import html
import json
from pathlib import Path
from collections import defaultdict
import numpy as np
from .config import config_from_dict
from .fusion import FusionEngine
from .models import Ray
from .recording import CSVRecorder,dumps


def read_csv(path: str | Path) -> list[dict[str,str]]:
    with Path(path).open(encoding="utf-8-sig",newline="") as stream:
        return list(csv.DictReader(stream))


def analyze_session(session: str | Path, plots: bool = True) -> dict:
    # path = Path(session).resolve()
    path = Path(session).expanduser()

    # 原路径下找不到实验元数据时，再到项目 runs 目录查找。
    if not path.is_absolute() and not (path / "metadata.json").is_file():
        project_root = Path(__file__).resolve().parents[1]
        candidate = project_root / "runs" / path

        if (candidate / "metadata.json").is_file():
            path = candidate

    path = path.resolve()
    metadata = json.loads((path/"metadata.json").read_text(encoding="utf-8"))
    if (path/"manifest.sha256.json").exists():
        manifest = json.loads((path/"manifest.sha256.json").read_text())
        corrupt = [name for name,sha in manifest.items() if not (path/name).is_file()
                   or hashlib.sha256((path/name).read_bytes()).hexdigest()!=sha]
        if corrupt:
            raise ValueError(f"日志文件完整性校验失败: {corrupt}")
    cycles = read_csv(path/"cycles.csv")
    latencies = np.asarray([float(row["work_ms"]) for row in cycles])
    commands = read_csv(path/"commands.csv")
    tracks = read_csv(path/"tracks.csv")
    metrics = json.loads(cycles[-1]["metrics_json"]) if cycles else {}
    summary = {"run_id":metadata["run_id"],"mode":metadata["mode"],"completed":metadata["completed"],
        "cycles":len(cycles),"duration_s":float(cycles[-1]["t_s"])+float(cycles[-1]["dt_s"]) if cycles else 0,
        "cycle_ms_p50":float(np.percentile(latencies,50)) if len(latencies) else None,
        "cycle_ms_p95":float(np.percentile(latencies,95)) if len(latencies) else None,
        "cycle_ms_max":float(max(latencies)) if len(latencies) else None,
        "deadline_misses":sum(row["deadline_miss"]=="True" for row in cycles),
        "localizations":sum(int(row["localizations"]) for row in cycles),
        "track_ids":len({row["track_id"] for row in tracks}),
        "command_errors":sum(bool(row["error"]) for row in commands),"final_metrics":metrics}
    (path/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    if plots and cycles:
        try:
            _plots(path,cycles,tracks,metadata)
        except ImportError:
            summary["plot_note"] = "安装 .[analysis] 生成 PNG/PDF 图表"
    rows = "".join(f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>"
                   for k,v in summary.items() if k!="final_metrics")
    rows += "".join(f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>" for k,v in metrics.items())
    images = "".join(f'<figure><img src="{name}.png" alt="{name}"></figure>'
                     for name in ("trajectories","device_angles","task_metrics") if (path/f"{name}.png").exists())
    report = f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>ZR10 实验报告</title>
<style>body{{max-width:1120px;margin:40px auto;font:16px system-ui;color:#172638;background:#f5f7fa}}
h1{{color:#064c62}}table{{border-collapse:collapse;background:white;width:100%}}td{{padding:8px 16px;border-bottom:1px solid #ddd}}img{{width:100%}}figure{{margin:24px 0}}</style>
<h1>ZR10 协同观测 · 实验报告</h1><p>{html.escape(metadata['run_id'])}</p>
<p>测量轨迹与预测轨迹分别记录。仿真真值用于评估，不进入算法观测。周期耗时包含几何、融合、策略、指标与日志入队，不包含相机曝光和网络延迟。</p>
<table>{rows}</table>{images}</html>'''
    (path/"report.html").write_text(report,encoding="utf-8")
    return summary


def _plots(path,cycles,tracks,metadata):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"figure.dpi":130,"axes.grid":True,"grid.alpha":.2})
    fig = plt.figure(figsize=(10,7))
    ax = fig.add_subplot(111,projection="3d")
    groups = defaultdict(list)
    for row in tracks:
        groups[row["track_id"]].append(row)
    for key,items in groups.items():
        pos = np.array([[float(r[c]) for c in ("x_m","y_m","z_m")] for r in items])
        ax.plot(*pos.T,label=key,lw=1.3)
        predicted = np.array([r["measured"]!="True" for r in items])
        if predicted.any():
            ax.scatter(*pos[predicted].T,marker="x",s=15)
    truth = defaultdict(list)
    for row in read_csv(path/"truth.csv"):
        truth[row["truth_id"]].append([float(row[c]) for c in ("x_m","y_m","z_m")])
    for key,items in truth.items():
        ax.plot(*np.array(items).T,"--",alpha=.6,label="truth "+key)
    for d in metadata["config"]["devices"]:
        if d.get("enabled",True):
            ax.scatter(*d["position_m"],marker="^",s=60,color="#064c62")
            ax.text(*d["position_m"],d["id"],fontsize=8)
    ax.set(xlabel="East x / m",ylabel="North y / m",zlabel="Up z / m",title="3D trajectories (x: predicted samples)")
    if groups or truth:
        ax.legend(fontsize=8)
    fig.tight_layout()
    for suffix in ("png","pdf"):
        fig.savefig(path/f"trajectories.{suffix}")
    plt.close(fig)
    fig,axes = plt.subplots(3,1,figsize=(11,8),sharex=True)
    by_device = defaultdict(list)
    for row in read_csv(path/"telemetry.csv"):
        by_device[row["device_id"]].append(row)
    for key,items in by_device.items():
        ts = [float(r["t_s"]) for r in items]
        for ax,col in zip(axes,("yaw_deg","pitch_deg","zoom")):
            ax.plot(ts,[float(r[col]) for r in items],label=key)
            ax.set_ylabel(col)
    axes[0].legend(ncol=4)
    axes[-1].set_xlabel("Experiment time / s")
    fig.tight_layout(); fig.savefig(path/"device_angles.png"); plt.close(fig)
    ts = [float(r["t_s"]) for r in cycles]
    metric_rows = [json.loads(r["metrics_json"]) for r in cycles]
    fig,axes = plt.subplots(2,1,figsize=(11,6),sharex=True)
    for col in ("roi_cumulative_coverage","roi_multiview_fraction","localization_recall"):
        if any(col in r for r in metric_rows):
            axes[0].plot(ts,[r.get(col,np.nan) for r in metric_rows],label=col)
    axes[0].legend(); axes[0].set_ylabel("Fraction")
    axes[1].plot(ts,[float(r["work_ms"]) for r in cycles],label="processing ms")
    axes[1].axhline(1000*float(cycles[0]["dt_s"]),color="r",ls="--",label="cycle budget")
    axes[1].legend(); axes[1].set(xlabel="Experiment time / s",ylabel="ms")
    fig.tight_layout(); fig.savefig(path/"task_metrics.png"); plt.close(fig)


def replay_session(session: str | Path, output: str | Path, fusion_overrides=None) -> Path:
    """按原周期重新处理已记录射线。可替换融合门限；不伪称改变过去控制动作。"""
    path = Path(session)
    metadata = json.loads((path/"metadata.json").read_text(encoding="utf-8"))
    cfg = config_from_dict(metadata["config"])
    cfg.fusion.update(fusion_overrides or {})
    engine = FusionEngine(cfg.fusion)
    recorder = CSVRecorder(output,cfg.to_dict(),"replay",metadata["start_t"])
    by_t = defaultdict(list)
    for row in read_csv(path/"rays.csv"):
        embed = json.loads(row.get("embedding_json") or "null")
        ray = Ray(row["device_id"],row["detection_id"],float(row["capture_t"]),
            tuple(float(row[k]) for k in ("ox","oy","oz")),tuple(float(row[k]) for k in ("dx","dy","dz")),
            float(row["confidence"]),float(row["angular_std_deg"]),int(row.get("class_id") or 0),
            float(row.get("time_uncertainty_s") or 0),tuple(embed) if embed else None)
        by_t[float(row["t_s"])].append(ray)
    completed = False
    try:
        recorder.event("replay_source",{"path":str(path.resolve()),"source_run":metadata["run_id"]},metadata["start_t"])
        for cycle in read_csv(path/"cycles.csv"):
            elapsed = float(cycle["t_s"])
            t = elapsed+metadata["start_t"]
            tracks,locations,diag = engine.update(by_t[elapsed],t)
            for tr in tracks:
                x,y,z = tr.position; vx,vy,vz = tr.velocity
                recorder.write("tracks",t,track_id=tr.track_id,estimate_t=tr.t,x_m=x,y_m=y,z_m=z,
                    vx_mps=vx,vy_mps=vy,vz_mps=vz,last_seen_t=tr.last_seen_t,hits=tr.hits,status=tr.status,
                    measured=tr.measured,device_ids_json=dumps(tr.device_ids),covariance_json=dumps(tr.covariance))
            for i,loc in enumerate(locations):
                x,y,z = loc.position
                recorder.write("localizations",t,localization_id=f"{cycle['step']}:{i}",measurement_t=loc.t,x_m=x,y_m=y,z_m=z,
                    device_ids_json=dumps(loc.device_ids),detection_ids_json=dumps(loc.detection_ids),residual_m=loc.residual_m,
                    min_angle_deg=loc.min_angle_deg,condition_number=loc.condition_number,time_span_s=loc.time_span_s,
                    covariance_json=dumps(loc.covariance))
            recorder.write("cycles",t,step=cycle["step"],dt_s=cycle["dt_s"],work_ms=0,deadline_miss=False,
                detections=0,rays=len(by_t[elapsed]),localizations=len(locations),tracks=len(tracks),
                measured_tracks=sum(tr.measured for tr in tracks),metrics_json="{}",diagnostics_json=dumps(diag))
        completed = True
    finally:
        recorder.close(completed)
    return recorder.path
