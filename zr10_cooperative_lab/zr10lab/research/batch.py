from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np

from ..config import load_config
from .runner import run_research_simulation


DEFAULT_METHODS = (
    "fixed_scan", "greedy", "weighted_rh", "classical_ptz",
    "info_planner", "ssm_belief", "ecprh",
)


def _last_cycle_metrics(run_dir: Path) -> dict:
    path = run_dir / "cycles.csv"
    last = None
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            last = row
    if last is None:
        return {}
    try:
        return json.loads(last.get("metrics_json") or "{}")
    except json.JSONDecodeError:
        return {}


def _solver_summary(run_dir: Path) -> dict:
    path = run_dir / "research_solver.csv"
    if not path.exists():
        return {}
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows.extend(csv.DictReader(stream))
    if not rows:
        return {"solve_count": 0}
    solve = [float(r["solve_ms"]) for r in rows if r.get("solve_ms") not in (None, "")]
    timeout = [str(r.get("timeout", "")).lower() in ("1", "true", "yes") for r in rows]
    gap = [float(r["mip_gap"]) for r in rows if r.get("mip_gap") not in (None, "")]
    visibility_certified = []
    priority_certified = []
    weighted_certified = []
    for row in rows:
        try:
            extras = json.loads(row.get("extras_json") or "{}")
        except json.JSONDecodeError:
            extras = {}
        if "visibility_level_certified" in extras:
            visibility_certified.append(bool(extras["visibility_level_certified"]))
        if "priority_certified" in extras:
            priority_certified.append(bool(extras["priority_certified"]))
        if "weighted_objective_certified" in extras:
            weighted_certified.append(bool(extras["weighted_objective_certified"]))
    return {
        "solve_count": len(rows),
        "solve_ms_mean": float(np.mean(solve)) if solve else None,
        "solve_ms_p95": float(np.percentile(solve, 95)) if solve else None,
        "solve_ms_max": float(np.max(solve)) if solve else None,
        "solver_timeout_rate": float(np.mean(timeout)) if timeout else None,
        "mip_gap_mean": float(np.mean(gap)) if gap else None,
        "mip_gap_max": float(np.max(gap)) if gap else None,
        "visibility_level_certification_rate": (float(np.mean(visibility_certified))
                                                 if visibility_certified else None),
        "priority_certification_rate": (float(np.mean(priority_certified))
                                         if priority_certified else None),
        "weighted_objective_certification_rate": (float(np.mean(weighted_certified))
                                                    if weighted_certified else None),
    }


def _write_table(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def aggregate(index_rows: list[dict], output: Path) -> list[dict]:
    """Create paper-ready mean/std/95%-CI summaries from completed Monte Carlo runs."""
    metric_rows = []
    for row in index_rows:
        if row.get("status") != "completed":
            continue
        run = Path(row["run_dir"])
        metrics = _last_cycle_metrics(run)
        metrics.update(_solver_summary(run))
        metric_rows.append({**row, **metrics})
    _write_table(output / "run_metrics.csv", metric_rows)
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in metric_rows:
        groups.setdefault((row["scenario"], row["method"]), []).append(row)
    summary = []
    metadata = {"scenario", "method", "seed", "run_dir", "status", "config"}
    for (scenario, method), rows in sorted(groups.items()):
        keys = sorted({k for r in rows for k, v in r.items()
                       if k not in metadata and isinstance(v, (int, float)) and not isinstance(v, bool)})
        for key in keys:
            values = np.asarray([float(r[key]) for r in rows
                                 if isinstance(r.get(key), (int, float)) and math.isfinite(float(r[key]))], dtype=float)
            if not len(values):
                continue
            mean = float(values.mean())
            std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
            ci = 1.96 * std / math.sqrt(len(values)) if len(values) > 1 else 0.0
            summary.append({
                "scenario": scenario, "method": method, "metric": key, "n": len(values),
                "mean": mean, "std": std, "ci95_low": mean-ci, "ci95_high": mean+ci,
                "min": float(values.min()), "max": float(values.max()),
            })
    _write_table(output / "summary_long.csv", summary)
    return metric_rows


def run_batch(scenarios: Iterable[str | Path], methods=DEFAULT_METHODS, seeds=range(10),
              output="runs/research_batch", continue_on_error=True):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []
    for scenario_path in scenarios:
        scenario_path = Path(scenario_path).resolve()
        base_cfg = load_config(scenario_path)
        scenario = str(base_cfg.policy.get("research", {}).get("scenario", {}).get("id", scenario_path.stem))
        for seed in seeds:
            for method in methods:
                row = {"scenario": scenario, "method": str(method), "seed": int(seed),
                       "config": str(scenario_path), "status": "running", "run_dir": ""}
                index.append(row)
                _write_table(root / "index.csv", index)
                try:
                    run_dir = run_research_simulation(base_cfg, method=str(method), output=root / "runs", seed=int(seed))
                    row["run_dir"] = str(Path(run_dir).resolve())
                    row["status"] = "completed"
                except Exception as exc:
                    row["status"] = "failed"
                    row["error"] = f"{type(exc).__name__}: {exc}"
                    if not continue_on_error:
                        _write_table(root / "index.csv", index)
                        raise
                _write_table(root / "index.csv", index)
    aggregate(index, root)
    return root


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run persistent-search comparison experiments")
    parser.add_argument("scenarios", nargs="+", help="Scenario YAML files")
    parser.add_argument("--methods", nargs="+", default=list(DEFAULT_METHODS))
    parser.add_argument("--seeds", nargs="+", type=int, default=list(range(10)))
    parser.add_argument("--output", default="runs/research_batch")
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args(argv)
    root = run_batch(args.scenarios, args.methods, args.seeds, args.output, not args.fail_fast)
    print(root)


if __name__ == "__main__":
    main()
