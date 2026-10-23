from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from zr10lab.research.result_audit import audit_main_test


MANIFEST = Path("configs/research/paper_experiment_manifest.yaml")


def _write(path: Path, rows: list[dict]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _synthetic_tables(tmp_path: Path):
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    methods = manifest["methods"]["primary"]
    reference = manifest["statistics"]["reference_method"]
    scenarios = [Path(x).stem for x in manifest["splits"]["test_main"]["scenarios"]]
    seeds = manifest["splits"]["test_main"]["seeds"]
    primary = [x["name"] for x in manifest["metrics"]["primary"]]

    runs = []
    for scenario in scenarios:
        for seed in seeds:
            for method_index, method in enumerate(methods):
                row = {"scenario": scenario, "seed": seed, "method": method}
                for metric_index, metric in enumerate(primary):
                    row[metric] = float(method_index + metric_index)
                # Monitoring visibility is undefined in the no-target scenario.
                row["research_monitor_visible_ratio"] = (
                    "nan" if scenario == "S0_no_target" else 0.5 + 0.01 * method_index
                )
                runs.append(row)

    comparisons = []
    competitors = [x for x in methods if x != reference]
    scopes = [("overall", "__all__", 80)] + [
        ("scenario", scenario, 20) for scenario in scenarios
    ]
    for metric in primary:
        for competitor in competitors:
            for scope, scenario, n_pairs in scopes:
                comparisons.append({
                    "scope": scope,
                    "scenario": scenario,
                    "metric": metric,
                    "direction": "minimize",
                    "reference": reference,
                    "competitor": competitor,
                    "n_pairs": n_pairs,
                })

    # This conditional secondary metric legitimately has only 60 overall pairs:
    # 3 target-containing scenarios x 20 seeds.
    comparisons.append({
        "scope": "overall",
        "scenario": "__all__",
        "metric": "research_monitor_visible_ratio",
        "direction": "maximize",
        "reference": reference,
        "competitor": competitors[0],
        "n_pairs": 60,
    })

    run_path = tmp_path / "run_metrics.csv"
    comparison_path = tmp_path / "paired_comparisons.csv"
    _write(run_path, runs)
    _write(comparison_path, comparisons)
    return run_path, comparison_path, comparisons


def test_audit_accepts_conditionally_defined_secondary_pair_counts(tmp_path):
    run_path, comparison_path, _ = _synthetic_tables(tmp_path)
    report = audit_main_test(run_path, comparison_path, MANIFEST)
    assert report["actual_total_runs"] == 560
    assert report["primary_comparison_rows"] == 150
    assert report["conditional_secondary_n_pairs"]["research_monitor_visible_ratio"] == {
        "min": 60,
        "max": 60,
    }


def test_audit_rejects_padding_conditional_secondary_metric_to_80(tmp_path):
    run_path, comparison_path, comparisons = _synthetic_tables(tmp_path)
    comparisons[-1]["n_pairs"] = 80
    _write(comparison_path, comparisons)
    with pytest.raises(AssertionError, match="n_pairs mismatch"):
        audit_main_test(run_path, comparison_path, MANIFEST)
