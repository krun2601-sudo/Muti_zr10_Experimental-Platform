from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np

from ..config import load_config
from .batch import _last_cycle_metrics, _write_table
from .runner import run_research_simulation


OBJECTIVES = (
    "research_total_loss_s",
    "research_detection_delay_mean_s",
    "research_revisit_age_p95_s",
)


def _dominates(a, b):
    values_a = np.asarray([a[k] for k in OBJECTIVES], dtype=float)
    values_b = np.asarray([b[k] for k in OBJECTIVES], dtype=float)
    return np.all(values_a <= values_b + 1e-12) and np.any(values_a < values_b - 1e-12)


def tune_weighted_rh(validation_configs, seeds=(101, 102, 103),
                     loss_weights=(1.0, 3.0, 10.0, 30.0, 100.0),
                     overlap_weights=(1.0, 3.0, 10.0),
                     search_weights=(0.3, 1.0, 3.0),
                     motion_weights=(0.0, 0.03, 0.1),
                     output="runs/weighted_tuning"):
    """Tune weighted RH only on validation scenarios, never held-out tests.

    Weighted RH uses the same target-loss, soft-overlap, search and execution
    variables as ECP-RH. Its four finite weights are selected without looking at
    test data. The full grid and Pareto set are preserved for auditability.
    """
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=True)
    rows = []
    configurations = [Path(p).resolve() for p in validation_configs]
    grid = itertools.product(loss_weights, overlap_weights, search_weights, motion_weights)
    for loss_w, overlap_w, search_w, motion_w in grid:
        run_metrics = []
        for config_path in configurations:
            for seed in seeds:
                cfg = load_config(config_path)
                weights = cfg.policy.setdefault("research", {}).setdefault("baselines", {}).setdefault("weighted_rh", {})
                weights.update(
                    loss_weight=float(loss_w), overlap_weight=float(overlap_w),
                    search_weight=float(search_w), motion_weight=float(motion_w),
                )
                run_dir = run_research_simulation(cfg, "weighted_rh", root / "runs", int(seed))
                run_metrics.append(_last_cycle_metrics(Path(run_dir)))
        summary = {
            "loss_weight": float(loss_w), "overlap_weight": float(overlap_w),
            "search_weight": float(search_w), "motion_weight": float(motion_w),
            "runs": len(run_metrics),
        }
        for key in OBJECTIVES:
            values = [m.get(key) for m in run_metrics if isinstance(m.get(key), (int, float))]
            summary[key] = float(np.mean(values)) if values else float("inf")
        rows.append(summary)
        _write_table(root / "tuning_raw.csv", rows)

    finite = [row for row in rows if all(np.isfinite(row[key]) for key in OBJECTIVES)]
    if not finite:
        raise RuntimeError("weighted RH tuning produced no finite validation objective set")
    pareto = [row for row in finite
              if not any(_dominates(other, row) for other in finite if other is not row)]
    mins = {key: min(row[key] for row in finite) for key in OBJECTIVES}
    maxs = {key: max(row[key] for row in finite) for key in OBJECTIVES}
    for row in pareto:
        distance = 0.0
        for key in OBJECTIVES:
            span = maxs[key] - mins[key]
            if span > 1e-12:
                distance += ((row[key] - mins[key]) / span) ** 2
        row["normalized_ideal_distance"] = float(np.sqrt(distance))
    selected = min(pareto, key=lambda row: row["normalized_ideal_distance"])
    _write_table(root / "pareto.csv", pareto)
    (root / "selected.json").write_text(json.dumps({
        "selection_rule": "nearest normalized Pareto point to validation ideal",
        "validation_configs": [str(p) for p in configurations],
        "validation_seeds": [int(s) for s in seeds],
        "objectives_minimize": list(OBJECTIVES),
        "selected": selected,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return selected


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tune weighted RH-MPC on validation scenarios only")
    parser.add_argument("configs", nargs="+", help="Validation YAML files; never pass held-out test files")
    parser.add_argument("--seeds", nargs="+", type=int, default=[101, 102, 103])
    parser.add_argument("--output", default="runs/weighted_tuning")
    args = parser.parse_args(argv)
    print(json.dumps(tune_weighted_rh(args.configs, args.seeds, output=args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
