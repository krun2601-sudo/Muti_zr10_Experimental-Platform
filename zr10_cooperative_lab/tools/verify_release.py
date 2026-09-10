"""可重复的离线验收；不会连接设备、下载权重或访问外部服务。"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

# 可直接 python tools/verify_release.py，也可安装包后运行。
PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT / "tests" / "fixtures"
# 性能阈值对应固定基准，不读用户已修改的设备坐标、ROI 或无人机轨迹。
# 所有时长/初始角变换在报告中保存，避免存在未记录的“特殊调参”。
SCENARIOS = (
    ("multi", "release_base.yaml", 60),
    ("center", "release_center.yaml", 60),
    ("outage", "release_outage.yaml", 25),
    ("scan", "release_scan.yaml", 20),
    ("blind_start", "release_base.yaml", 15),
)
sys.path.insert(0,str(PROJECT))
from zr10lab.analysis import analyze_session,read_csv,replay_session
from zr10lab.config import load_config
from zr10lab.runtime import run_simulation


def file_hashes(paths):
    """文件原始字节的摘要；只用于追溯，不改写任何现场配置。"""
    return {path.relative_to(PROJECT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths) if path.is_file()}


def baseline_config(name, filename, duration):
    """加载固定场景及显式变换，返回可写入验收报告的变换说明。"""
    cfg = load_config(FIXTURES / filename)
    overrides = {"system.duration_s": duration}
    cfg.system["duration_s"] = duration
    if name == "blind_start":
        overrides["devices[*].initial_yaw_deg"] = -80
        for device in cfg.devices:
            device.initial_yaw_deg = -80
    return cfg, overrides


def main():
    output = PROJECT/"samples"/"validation"
    output.mkdir(parents=True,exist_ok=True)
    started = time.perf_counter()
    baseline_paths = list(FIXTURES.glob("release_*"))
    baseline_hashes = file_hashes(baseline_paths)
    user_paths = list((PROJECT / "configs").rglob("*.yaml")) + list((PROJECT / "configs").rglob("*.yml"))
    user_paths.append(PROJECT / "examples" / "calibration_controls_example.csv")
    user_hashes = file_hashes(user_paths)
    tests = subprocess.run([sys.executable,"-B","-m","pytest","-q","-p","no:cacheprovider"],
                           cwd=PROJECT,capture_output=True,text=True,encoding="utf-8",errors="replace")
    (output/"pytest.txt").write_text(tests.stdout+tests.stderr,encoding="utf-8")
    print(tests.stdout,flush=True)
    if tests.returncode:
        raise RuntimeError("测试失败，停止发布验收")
    scenarios = []
    for name,filename,duration in SCENARIOS:
        cfg, overrides = baseline_config(name, filename, duration)
        path = run_simulation(cfg,output/name)
        summary = analyze_session(path,plots=True)
        cycles = read_csv(path/"cycles.csv")
        measured_cycles = [r for r in cycles if int(r["measured_tracks"])>0]
        summary["first_localization_s"] = float(measured_cycles[0]["t_s"]) if measured_cycles else None
        summary["scenario"] = name
        summary["session"] = path.relative_to(PROJECT).as_posix()
        summary["baseline_config"] = (FIXTURES / filename).relative_to(PROJECT).as_posix()
        summary["configuration_overrides"] = overrides
        assert summary["completed"]
        if name in ("multi","center"):
            assert summary["final_metrics"]["cumulative_localization_recall"]>.95
            assert summary["final_metrics"]["position_rmse_m"]<1
        if name=="outage":
            rows = read_csv(path/"telemetry.csv")
            assert any(r["connected"]=="False" for r in rows)
            assert summary["final_metrics"]["localization_recall"]==1
        if name=="scan":
            assert summary["localizations"]==0
            assert summary["final_metrics"]["roi_cumulative_coverage"]>.5
        if name=="blind_start":
            assert summary["first_localization_s"] is not None and summary["first_localization_s"]<8
        scenarios.append(summary)
        print(json.dumps(summary,ensure_ascii=False),flush=True)
    original = PROJECT/scenarios[0]["session"]
    replay = replay_session(original,output/"replay")
    left,right = read_csv(original/"tracks.csv"),read_csv(replay/"tracks.csv")
    assert len(left)==len(right)
    maximum_difference = 0.
    for a,b in zip(left,right):
        assert a["track_id"]==b["track_id"] and a["measured"]==b["measured"]
        maximum_difference = max(maximum_difference,*(abs(float(a[k])-float(b[k])) for k in ("x_m","y_m","z_m")))
    assert maximum_difference<1e-8
    calibration_path = output/"mount_fit_example.json"
    calibration = subprocess.run([sys.executable,"-B","-m","zr10lab.calibration","mount",
        "--config",str(FIXTURES / "release_base.yaml"),"--device","zr10_25",
        "--csv",str(FIXTURES / "release_calibration_controls.csv"),
        "--output",str(calibration_path)],cwd=PROJECT,capture_output=True,text=True,encoding="utf-8",errors="replace")
    assert calibration.returncode==0,calibration.stdout+calibration.stderr
    fitted = json.loads(calibration_path.read_text(encoding="utf-8"))
    assert fitted["success"] and fitted["rms_angle_deg"]<.01
    dependencies = subprocess.check_output([sys.executable,"-m","pip","freeze"],text=True,encoding="utf-8")
    (output/"environment.txt").write_text(dependencies,encoding="utf-8")
    # 将前端、第三方固定资源和安装声明也纳入验收，避免只验证Python源码却
    # 漏掉已更改的界面/依赖。测试环境完整不代表发布包自动包含这些文件。
    tracked_files = [p for folder in ("zr10lab", "tests", "configs", "tools", "docs")
                     for p in sorted((PROJECT / folder).rglob("*")) if p.is_file()
                     and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".bak")]
    tracked_files += [PROJECT / name for name in ("pyproject.toml", "requirements.txt", "README_v4.md", "启动控制中心.cmd")]
    source_hashes = file_hashes(tracked_files)
    if file_hashes(baseline_paths) != baseline_hashes:
        raise RuntimeError("固定验收基准在执行期间发生变化；本次结果不可发布，请在基准稳定后重跑")
    result = {"status":"passed","python":platform.python_version(),"platform":platform.platform(),
        "test_output":tests.stdout.strip(),"scenarios":scenarios,
        "baseline_sha256": baseline_hashes,
        "baseline_description": "五个仿真性能场景与示例标定读取 tests/fixtures/release_* 固定基准；不读取现场配置作为阈值输入",
        "user_configuration_sha256": user_hashes,
        "user_configuration_changed_during_validation": file_hashes(user_paths) != user_hashes,
        "replay_rows":len(left),"replay_max_position_difference_m":maximum_difference,
        "replay_session":replay.relative_to(PROJECT).as_posix(),
        "calibration_angular_rmse_deg":fitted["rms_angle_deg"],"elapsed_wall_s":time.perf_counter()-started,
        "hardware_tested":False,"user_yolo_model_tested":False,"source_sha256":source_hashes}
    (output/"VERIFICATION.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    lines = ["# 离线验收结果","",f"Python {result['python']}；{result['platform']}","",tests.stdout.strip(),"",
        "性能阈值使用 tests/fixtures/release_* 固定基准；现场 configs/ 的修改不会改变这五个场景或示例标定输入。",
        "VERIFICATION.json 保存每个基准文件及现场配置原始字节的 SHA256、场景文件和显式时长/初始角变换；现场配置不会被本脚本改写。","",
        "| 场景 | 周期 | 首次定位(s) | 定位覆盖率 | RMSE(m) | ID切换 | 周期P95(ms) |",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for s in scenarios:
        m=s["final_metrics"]
        lines.append(f"| {s['scenario']} | {s['cycles']} | {s['first_localization_s']} | {m.get('cumulative_localization_recall')} | {m.get('position_rmse_m')} | {m.get('id_switches')} | {s['cycle_ms_p95']:.2f} |")
    lines += ["",f"原始射线重放 {len(left)} 条轨迹输出，位置最大差 {maximum_difference:g} m。",
              f"示例控制点安装姿态拟合角RMSE {fitted['rms_angle_deg']:.8f} deg。","",
              "本次为离线软件/模拟SDK验收；没有实机连接、你的YOLO权重或真实采集图像的验证。",
              "仿真精度不代表现场精度。每个场景子目录包含实际CSV、report.html、PNG/PDF及元数据。"]
    (output/"验收报告.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(f"VERIFICATION PASSED: {output}",flush=True)


if __name__=="__main__":
    main()
