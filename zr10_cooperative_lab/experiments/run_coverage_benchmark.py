"""批量运行严格覆盖基线；每个算法/场景/seed 都创建独立实验会话。"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
from pathlib import Path
import traceback

from zr10lab.config import load_config, validate_config
from zr10lab.runtime import run_hardware, run_simulation

ALGORITHMS = {
    "fs": "zr10lab.algorithms.fixed_sweep:FixedSweepPolicy",
    "ewp": "zr10lab.algorithms.equal_workload:EqualWorkloadPolicy",
    "cg": "zr10lab.algorithms.cooperative_greedy:CooperativeGreedyPolicy",
    "tvp": "zr10lab.algorithms.time_aware_partition:TimeAwarePartitionPolicy",
    "vgls": "zr10lab.algorithms.viewpoint_local_search:ViewpointLocalSearchPolicy",
    "opt": "zr10lab.algorithms.optimal_reference:OptimalReferencePolicy",
    "proposed": "zr10lab.algorithms.proposed:ProposedCoveragePolicy",
}


def _csv(value: str):
    return [x.strip() for x in value.split(",") if x.strip()]


def _seeds(value: str):
    return [int(x) for x in _csv(value)]


def _prepare(base, algorithm: str, seed: int, scenario_id: str):
    cfg = copy.deepcopy(base)
    cfg.policy.update(name="custom", custom=ALGORITHMS[algorithm], algorithm_id=algorithm,
                      policy_seed=seed, scenario_id=scenario_id)
    cfg.simulation["seed"] = seed
    if algorithm == "opt":
        cfg.policy.setdefault("opt_time_limit_s", 60.0)
        cfg.policy.setdefault("opt_max_viewpoints_per_device", 10)
    validate_config(cfg)
    return cfg


def main(argv=None):
    parser = argparse.ArgumentParser(description="运行多固定光电设备严格覆盖 benchmark")
    parser.add_argument("--algorithms", default="fs,ewp,cg,tvp,vgls,opt",
                        help="逗号分隔: fs,ewp,cg,tvp,vgls,opt,proposed")
    parser.add_argument("--scenario-configs", nargs="+", default=["configs/coverage_common.yaml"],
                        help="一个或多个场景YAML；算法入口会在内存副本上覆盖，不改原文件")
    parser.add_argument("--seeds", default="7", help="逗号分隔随机种子；确定性算法用于环境/追溯，VGLS也作为policy_seed")
    parser.add_argument("--mode", choices=("sim", "hardware"), default="sim")
    parser.add_argument("--output", default="benchmark_runs")
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--realtime", action="store_true")
    parser.add_argument("--arm", action="store_true", help="批量实机运行仍需显式 --arm")
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args(argv)

    algorithms = _csv(args.algorithms)
    unknown = sorted(set(algorithms) - set(ALGORITHMS))
    if unknown:
        raise ValueError(f"未知算法: {unknown}")
    if args.mode == "hardware" and not args.arm:
        raise ValueError("hardware benchmark 必须显式提供 --arm")
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"mode": args.mode, "algorithms": algorithms, "seeds": _seeds(args.seeds),
                "scenario_configs": [str(Path(x).resolve()) for x in args.scenario_configs], "runs": []}

    for scenario_path in args.scenario_configs:
        base = load_config(scenario_path)
        scenario_id = str(base.policy.get("scenario_id", Path(scenario_path).stem))
        if args.duration is not None:
            base.system["duration_s"] = float(args.duration)
        for seed in _seeds(args.seeds):
            for algorithm in algorithms:
                row = {"scenario_id": scenario_id, "algorithm_id": algorithm, "seed": seed,
                       "status": "started", "session": None, "error": None}
                print(f"[coverage] scenario={scenario_id} algorithm={algorithm} seed={seed}", flush=True)
                try:
                    cfg = _prepare(base, algorithm, seed, scenario_id)
                    session = (run_simulation(cfg, output, args.realtime) if args.mode == "sim"
                               else asyncio.run(run_hardware(cfg, output, armed=True)))
                    row.update(status="finished", session=str(session))
                except Exception as exc:
                    row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                    print(row["error"], flush=True)
                    traceback.print_exc()
                    if args.fail_fast:
                        manifest["runs"].append(row)
                        (output / "benchmark_manifest.json").write_text(
                            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                        raise
                manifest["runs"].append(row)
                (output / "benchmark_manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"benchmark manifest: {output / 'benchmark_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
