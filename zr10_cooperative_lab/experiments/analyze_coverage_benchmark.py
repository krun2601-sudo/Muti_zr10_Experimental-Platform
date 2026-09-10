"""汇总严格覆盖 benchmark。

只读原始会话文件，派生结果写到独立输出目录。若同一 scenario 的 problem_hash
不一致，默认拒绝横向排名。未完成运行的 Tcov 保持空值，不用实验时长冒充。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import mean, pstdev

import numpy as np


def _read_csv(path: Path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _json(text, default=None):
    try:
        return json.loads(text) if text else default
    except json.JSONDecodeError:
        return default


def _float(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _actual_slew(session: Path):
    rows = _read_csv(session / "telemetry.csv")
    by_device = {}
    for row in rows:
        by_device.setdefault(row["device_id"], []).append(row)
    total = 0.0
    for device_rows in by_device.values():
        device_rows.sort(key=lambda r: float(r["t_s"]))
        previous = None
        for row in device_rows:
            pose = (_float(row.get("yaw_deg")), _float(row.get("pitch_deg")))
            if None in pose:
                continue
            if previous is not None:
                total += math.hypot(pose[0] - previous[0], pose[1] - previous[1])
            previous = pose
    return total


def _last_cycle(session: Path):
    rows = _read_csv(session / "cycles.csv")
    return rows[-1] if rows else None


def _solver_info(session: Path):
    for row in _read_csv(session / "cycles.csv"):
        diag = _json(row.get("diagnostics_json"), {}) or {}
        policy = diag.get("policy", {}) if isinstance(diag, dict) else {}
        solver = policy.get("solver", {}) if isinstance(policy, dict) else {}
        if solver and solver.get("status") not in (None, "not_planned"):
            return solver, _float(policy.get("planning_ms"))
    return {}, None


def _run_record(session: Path, mc_samples: int, mc_seed: int):
    metadata_path = session / "metadata.json"
    if not metadata_path.exists():
        return None, []
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    last = _last_cycle(session)
    metrics = _json(last.get("metrics_json"), {}) if last else {}
    cells = _read_csv(session / "coverage_cells.csv")
    times = [_float(r.get("first_covered_t_s")) for r in cells]
    times = [x for x in times if x is not None]
    completed = bool(metadata.get("completed")) and bool(metrics.get("coverage_complete", False))
    tcov = _float(metadata.get("coverage_completion_time_s")) if completed else None
    if tcov is None and completed:
        tcov = _float(metrics.get("coverage_completion_time_s"))
    mean_first = float(np.mean(times)) if times else None
    p95_first = float(np.percentile(times, 95)) if times else None
    solver, planning_ms = _solver_info(session)

    credited = {}
    for row in cells:
        t = _float(row.get("first_covered_t_s"))
        if t is None:
            continue
        for did in (_json(row.get("device_ids_json"), []) or []):
            credited[str(did)] = max(credited.get(str(did), 0.0), t)

    cdf_rows = []
    detect_mean = detect_p95 = detect_max = None
    if times and mc_samples > 0:
        rng = np.random.default_rng(mc_seed)
        samples = rng.choice(np.asarray(times, dtype=float), size=int(mc_samples), replace=True)
        detect_mean = float(np.mean(samples)); detect_p95 = float(np.percentile(samples, 95)); detect_max = float(np.max(samples))
        for q in np.linspace(0, 1, 101):
            cdf_rows.append({"run_id": metadata.get("run_id", session.name), "quantile": float(q),
                             "detection_time_s": float(np.quantile(samples, q))})

    record = {
        "run_id": metadata.get("run_id", session.name),
        "session": str(session),
        "scenario_id": metadata.get("scenario_id", "default"),
        "algorithm_id": metadata.get("algorithm_id", "unknown"),
        "algorithm_version": metadata.get("algorithm_version", ""),
        "problem_hash": metadata.get("problem_hash", ""),
        "environment_seed": metadata.get("environment_seed"),
        "policy_seed": metadata.get("policy_seed"),
        "success": completed,
        "Tcov_s": tcov,
        "mean_first_coverage_s": mean_first,
        "p95_first_coverage_s": p95_first,
        "overlap_ratio": _float(metrics.get("coverage_overlap_ratio")),
        "slew_cost_actual_deg": _actual_slew(session),
        "device_completion_times_json": json.dumps(credited, ensure_ascii=False, separators=(",", ":")),
        "workload_std_s": _float(metrics.get("coverage_workload_std")),
        "planning_ms": planning_ms,
        "solver_status": solver.get("status", ""),
        "solver_best_bound_s": _float(solver.get("best_bound_s")),
        "solver_reported_gap": _float(solver.get("gap")),
        "gap_to_opt_pct": None,
        "mc_detection_mean_s": detect_mean,
        "mc_detection_p95_s": detect_p95,
        "mc_detection_max_s": detect_max,
        "termination_reason": metadata.get("termination_reason", ""),
    }
    return record, cdf_rows


def _write_csv(path: Path, rows):
    rows = list(rows)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    keys = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader(); writer.writerows(rows)


def _aggregate(rows):
    groups = {}
    for row in rows:
        key = (row["scenario_id"], row["problem_hash"], row["algorithm_id"])
        groups.setdefault(key, []).append(row)
    out = []
    numeric = ["Tcov_s", "mean_first_coverage_s", "p95_first_coverage_s", "overlap_ratio",
               "slew_cost_actual_deg", "workload_std_s", "planning_ms", "gap_to_opt_pct",
               "mc_detection_mean_s", "mc_detection_p95_s", "mc_detection_max_s"]
    for (scenario, phash, algorithm), items in sorted(groups.items()):
        row = {"scenario_id": scenario, "problem_hash": phash, "algorithm_id": algorithm,
               "runs": len(items), "successes": sum(bool(x["success"]) for x in items),
               "success_rate": sum(bool(x["success"]) for x in items) / len(items)}
        for key in numeric:
            values = [float(x[key]) for x in items if x.get(key) not in (None, "") and math.isfinite(float(x[key]))]
            row[f"{key}_mean"] = mean(values) if values else None
            row[f"{key}_std"] = pstdev(values) if len(values) > 1 else (0.0 if values else None)
        out.append(row)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="分析严格覆盖 benchmark")
    parser.add_argument("root", nargs="?", default="benchmark_runs")
    parser.add_argument("--output", default=None)
    parser.add_argument("--mc-samples", type=int, default=10000)
    parser.add_argument("--mc-seed", type=int, default=2601)
    parser.add_argument("--allow-mixed-problems", action="store_true",
                        help="只允许输出独立行；不同problem_hash仍不会互算Gap")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    output = Path(args.output).resolve() if args.output else root / "benchmark_analysis"
    output.mkdir(parents=True, exist_ok=True)
    sessions = sorted({p.parent for p in root.rglob("metadata.json") if p.parent != output})
    runs, cdf = [], []
    for i, session in enumerate(sessions):
        record, rows = _run_record(session, args.mc_samples, args.mc_seed + i)
        if record:
            runs.append(record); cdf.extend(rows)
    if not runs:
        raise ValueError(f"{root} 下没有可分析的实验会话")

    by_scenario = {}
    for r in runs:
        by_scenario.setdefault(r["scenario_id"], set()).add(r["problem_hash"])
    mixed = {k: v for k, v in by_scenario.items() if len(v - {""}) > 1}
    if mixed and not args.allow_mixed_problems:
        raise ValueError(f"同一scenario出现不同problem_hash，拒绝横向排名: {mixed}")

    # Gap 只使用 solver 明确证明 optimal 的 OPT 实际运行时间；time_limit 不冒充全局最优。
    opt = {}
    for r in runs:
        if r["algorithm_id"] == "opt" and r["success"] and r["solver_status"] == "optimal" and r["Tcov_s"] is not None:
            key = (r["scenario_id"], r["problem_hash"])
            opt[key] = min(opt.get(key, math.inf), float(r["Tcov_s"]))
    for r in runs:
        key = (r["scenario_id"], r["problem_hash"])
        if r["success"] and r["Tcov_s"] is not None and key in opt and opt[key] > 0:
            r["gap_to_opt_pct"] = (float(r["Tcov_s"]) - opt[key]) / opt[key] * 100.0

    _write_csv(output / "benchmark_runs.csv", runs)
    _write_csv(output / "benchmark_summary.csv", _aggregate(runs))
    _write_csv(output / "benchmark_detection_cdf.csv", cdf)
    print(output / "benchmark_runs.csv")
    print(output / "benchmark_summary.csv")
    print(output / "benchmark_detection_cdf.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
