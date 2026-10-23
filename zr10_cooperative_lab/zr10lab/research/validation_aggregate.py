from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .baseline_tuning import SELECTION_METRICS


EXPECTED_VALIDATION_SEEDS = (2001, 2002, 2003, 2004, 2005)
EXPECTED_VALIDATION_SCENARIOS = ("S4_boundary_handoff.yaml", "S8_maneuver.yaml")


def _finite_mean(series) -> float:
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    return float(np.mean(values)) if len(values) else float("inf")


def _score(row: dict) -> tuple[float, ...]:
    return tuple(float(row.get(metric, float("inf"))) for metric in SELECTION_METRICS)


def aggregate_method(root: Path, method: str, output: Path, *,
                     workflow_run_id: str | None = None,
                     data_commit_sha: str | None = None) -> Path:
    files = sorted(root.glob(f"**/{method}/seed_*/tuning_runs.csv"))
    if not files:
        # GitHub artifact extraction often removes the leading method directory.
        files = sorted(root.glob(f"**/seed_*/tuning_runs.csv"))
        files = [p for p in files if method in str(p.parent.parent)]
    if not files:
        raise FileNotFoundError(f"no tuning_runs.csv shards found for {method!r} under {root}")

    frames = []
    for path in files:
        frame = pd.read_csv(path, encoding="utf-8-sig")
        if "method" not in frame.columns or set(frame["method"].astype(str)) != {method}:
            raise ValueError(f"unexpected method contents in {path}")
        frames.append(frame)
    data = pd.concat(frames, ignore_index=True)

    seeds = tuple(sorted({int(x) for x in data["seed"].unique()}))
    if seeds != EXPECTED_VALIDATION_SEEDS:
        raise ValueError(
            f"{method}: validation seeds are {seeds}, expected {EXPECTED_VALIDATION_SEEDS}; "
            "refusing to freeze parameters from incomplete validation data"
        )

    if "config" not in data.columns:
        raise ValueError(f"{method}: validation data has no config column")
    scenario_names = tuple(sorted({Path(str(x)).name for x in data["config"].unique()}))
    if scenario_names != tuple(sorted(EXPECTED_VALIDATION_SCENARIOS)):
        raise ValueError(
            f"{method}: validation scenarios are {scenario_names}, expected "
            f"{tuple(sorted(EXPECTED_VALIDATION_SCENARIOS))}"
        )

    param_cols = sorted(c for c in data.columns if c.startswith("param_"))
    if not param_cols:
        raise ValueError(f"{method}: no param_* columns in validation data")

    # Every parameter tuple must have exactly both frozen validation scenarios for
    # every seed.  This catches partial/failed artifacts before model selection.
    expected_runs_per_tuple = len(EXPECTED_VALIDATION_SEEDS) * len(EXPECTED_VALIDATION_SCENARIOS)
    grouped = data.groupby(param_cols, dropna=False, sort=True)
    rows = []
    for params, block in grouped:
        if not isinstance(params, tuple):
            params = (params,)
        block_seeds = tuple(sorted({int(x) for x in block["seed"].unique()}))
        if block_seeds != EXPECTED_VALIDATION_SEEDS:
            raise ValueError(f"{method}: parameter tuple {params} is missing validation seeds")
        block_scenarios = tuple(sorted({Path(str(x)).name for x in block["config"].unique()}))
        if block_scenarios != tuple(sorted(EXPECTED_VALIDATION_SCENARIOS)):
            raise ValueError(f"{method}: parameter tuple {params} is missing validation scenarios")
        if len(block) != expected_runs_per_tuple:
            raise ValueError(
                f"{method}: parameter tuple {params} has {len(block)} runs; "
                f"expected {expected_runs_per_tuple} (2 scenarios x 5 seeds)"
            )
        row = {col: value for col, value in zip(param_cols, params)}
        row["runs"] = int(len(block))
        for metric in SELECTION_METRICS:
            if metric not in block.columns:
                raise ValueError(f"{method}: missing selection metric {metric}")
            row[metric] = _finite_mean(block[metric])
        rows.append(row)

    # The frozen manifest budgets exactly 24 deterministic tuples per method.
    if len(rows) != 24:
        raise ValueError(f"{method}: found {len(rows)} parameter tuples; expected exactly 24")

    selected = min(rows, key=_score)
    selected_params = {col.removeprefix("param_"): selected[col] for col in param_cols}
    document = {
        "method": method,
        "selection_rule": (
            "lexicographic validation means over S4/S8 and seeds 2001-2005: "
            "missed-target rate, censored detection-delay P95, post-discovery total loss, "
            "maximum loss gap, revisit-age P95"
        ),
        "selection_metrics": list(SELECTION_METRICS),
        "validation_configs": list(EXPECTED_VALIDATION_SCENARIOS),
        "validation_seeds": list(EXPECTED_VALIDATION_SEEDS),
        "evaluated_parameter_count": len(rows),
        "runs_per_parameter_tuple": expected_runs_per_tuple,
        "workflow_run_id": workflow_run_id,
        "data_commit_sha": data_commit_sha,
        "selected_params": selected_params,
        "selected_summary": selected,
        "source_files": [str(p) for p in files],
    }

    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / f"validation_summary_{method}.csv"
    pd.DataFrame(rows).sort_values(list(SELECTION_METRICS), kind="stable").to_csv(
        summary_path, index=False, encoding="utf-8-sig"
    )
    path = output / f"selected_{method}.json"
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Aggregate five-seed validation tuning shards")
    parser.add_argument("root", type=Path, help="root containing extracted validation shard artifacts")
    parser.add_argument("--methods", nargs="+", default=[
        "weighted_rh", "classical_ptz", "info_planner", "ssm_belief"
    ])
    parser.add_argument("--output", type=Path, default=Path("runs/validation_selected"))
    parser.add_argument("--workflow-run-id")
    parser.add_argument("--data-commit-sha")
    args = parser.parse_args(argv)

    for method in args.methods:
        print(aggregate_method(
            args.root.resolve(), method, args.output.resolve(),
            workflow_run_id=args.workflow_run_id,
            data_commit_sha=args.data_commit_sha,
        ))


if __name__ == "__main__":
    main()
