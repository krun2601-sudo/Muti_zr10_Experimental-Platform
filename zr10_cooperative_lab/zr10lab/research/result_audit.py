from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import yaml


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _scenario_id(config_path: str) -> str:
    return Path(config_path).stem


def audit_main_test(
    run_metrics_csv: str | Path,
    paired_comparisons_csv: str | Path,
    manifest_path: str | Path,
) -> dict:
    """Audit a frozen held-out main-test result without changing its statistics.

    Primary metrics are required to have a complete paired sample for every
    scenario/seed case. Conditional secondary metrics are *not* padded or filled;
    their reported ``n_pairs`` must instead equal the number of finite pairs that
    actually exists in ``run_metrics.csv``.
    """
    manifest = yaml.safe_load(Path(manifest_path).read_text(encoding="utf-8"))
    methods = [str(x) for x in manifest["methods"]["primary"]]
    reference = str(manifest["statistics"]["reference_method"])
    split = manifest["splits"]["test_main"]
    scenarios = [_scenario_id(x) for x in split["scenarios"]]
    seeds = [str(x) for x in split["seeds"]]
    primary = [str(x["name"]) for x in manifest["metrics"]["primary"]]

    if reference not in methods:
        raise AssertionError(f"reference method {reference!r} is not a primary method")

    runs = _read_csv(run_metrics_csv)
    expected_per_method = len(scenarios) * len(seeds)
    expected_total = len(methods) * expected_per_method
    if len(runs) != expected_total:
        raise AssertionError(f"expected {expected_total} held-out rows, got {len(runs)}")

    lookup: dict[tuple[str, str, str], dict[str, str]] = {}
    counts = {method: 0 for method in methods}
    scenario_counts = {(scenario, method): 0 for scenario in scenarios for method in methods}
    for row in runs:
        method = str(row.get("method", ""))
        scenario = str(row.get("scenario", ""))
        seed = str(row.get("seed", ""))
        if method not in counts:
            raise AssertionError(f"unexpected method {method!r}")
        if scenario not in scenarios:
            raise AssertionError(f"unexpected test_main scenario {scenario!r}")
        if seed not in seeds:
            raise AssertionError(f"unexpected test_main seed {seed!r}")
        key = (scenario, seed, method)
        if key in lookup:
            raise AssertionError(f"duplicate held-out row {key}")
        lookup[key] = row
        counts[method] += 1
        scenario_counts[(scenario, method)] += 1

    if any(value != expected_per_method for value in counts.values()):
        raise AssertionError(f"incomplete method shards: {counts}")
    expected_per_scenario = len(seeds)
    bad_scenario_counts = {key: value for key, value in scenario_counts.items()
                           if value != expected_per_scenario}
    if bad_scenario_counts:
        raise AssertionError(f"incomplete scenario/method cells: {bad_scenario_counts}")

    comparisons = _read_csv(paired_comparisons_csv)
    if not comparisons:
        raise AssertionError("paired comparison table is empty")

    comparison_keys = set()
    primary_expected_rows = set()
    for metric in primary:
        for competitor in methods:
            if competitor == reference:
                continue
            primary_expected_rows.add(("overall", "__all__", metric, competitor))
            for scenario in scenarios:
                primary_expected_rows.add(("scenario", scenario, metric, competitor))

    primary_seen = set()
    conditional_pair_counts: dict[str, list[int]] = {}
    for row in comparisons:
        scope = str(row.get("scope", ""))
        scenario_label = str(row.get("scenario", ""))
        metric = str(row.get("metric", ""))
        competitor = str(row.get("competitor", ""))
        row_reference = str(row.get("reference", ""))
        key = (scope, scenario_label, metric, competitor)
        if key in comparison_keys:
            raise AssertionError(f"duplicate paired-comparison row {key}")
        comparison_keys.add(key)
        if row_reference != reference:
            raise AssertionError(f"unexpected reference {row_reference!r} in {key}")
        if competitor not in methods or competitor == reference:
            raise AssertionError(f"unexpected competitor {competitor!r} in {key}")
        if scope not in {"overall", "scenario"}:
            raise AssertionError(f"unexpected scope {scope!r} in {key}")

        scenario_filter = scenarios if scope == "overall" else [scenario_label]
        if scope == "scenario" and scenario_label not in scenarios:
            raise AssertionError(f"unexpected scenario comparison {scenario_label!r}")

        finite_pairs = 0
        for scenario in scenario_filter:
            for seed in seeds:
                ref_row = lookup[(scenario, seed, reference)]
                other_row = lookup[(scenario, seed, competitor)]
                if _finite(ref_row.get(metric)) and _finite(other_row.get(metric)):
                    finite_pairs += 1
        reported_pairs = int(row["n_pairs"])
        if reported_pairs != finite_pairs:
            raise AssertionError(
                f"n_pairs mismatch for {key}: reported {reported_pairs}, finite raw pairs {finite_pairs}"
            )

        if metric in primary:
            expected_pairs = expected_per_method if scope == "overall" else expected_per_scenario
            if reported_pairs != expected_pairs:
                raise AssertionError(
                    f"primary metric {key} must have {expected_pairs} pairs, got {reported_pairs}"
                )
            primary_seen.add(key)
        else:
            conditional_pair_counts.setdefault(metric, []).append(reported_pairs)

    missing_primary = primary_expected_rows - primary_seen
    if missing_primary:
        preview = sorted(missing_primary)[:10]
        raise AssertionError(f"missing primary paired-comparison rows: {preview}")

    report = {
        "expected_total_runs": expected_total,
        "actual_total_runs": len(runs),
        "methods": methods,
        "scenarios": scenarios,
        "seeds_per_scenario": len(seeds),
        "runs_per_method": counts,
        "reference_method": reference,
        "primary_metrics": primary,
        "primary_comparison_rows": len(primary_seen),
        "comparison_rows": len(comparisons),
        "conditional_secondary_n_pairs": {
            metric: {"min": min(values), "max": max(values)}
            for metric, values in sorted(conditional_pair_counts.items()) if values
        },
        "status": "ok",
    }
    return report


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Audit frozen test_main completeness and paired-sample semantics"
    )
    parser.add_argument("run_metrics_csv")
    parser.add_argument("paired_comparisons_csv")
    parser.add_argument("--manifest", default="configs/research/paper_experiment_manifest.yaml")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    report = audit_main_test(args.run_metrics_csv, args.paired_comparisons_csv, args.manifest)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
