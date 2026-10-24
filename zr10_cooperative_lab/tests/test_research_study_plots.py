from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from zr10lab.research.study_plots import _mean_ci, scalability_figures


def test_bootstrap_interval_is_deterministic_and_contains_mean():
    values = [1.0, 2.0, 3.0, 5.0, 8.0]
    first = _mean_ci(values)
    second = _mean_ci(values)
    assert first == second
    mean, low, high, n = first
    assert n == len(values)
    assert np.isclose(mean, np.mean(values))
    assert low <= mean <= high


def test_scalability_figures_use_actual_frozen_csv_columns(tmp_path: Path):
    table = tmp_path / "scalability.csv"
    fields = [
        "device_count", "target_count", "search_candidates_per_device",
        "candidate_count", "generation_ms_p95", "solve_ms_p95",
        "priority_certification_rate",
    ]
    rows = []
    for targets in [0, 2, 4]:
        for search_candidates in [4, 8]:
            rows.append({
                "device_count": 4,
                "target_count": targets,
                "search_candidates_per_device": search_candidates,
                "candidate_count": 20 + 10 * targets + search_candidates,
                "generation_ms_p95": 30 + 20 * targets,
                "solve_ms_p95": 10 + 2 * targets,
                "priority_certification_rate": 1.0,
            })
    with table.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)

    output = tmp_path / "figures"
    generated = scalability_figures(table, output)
    names = {Path(path).name for path in generated}
    assert names == {
        "scalability_generation_ms_p95.png",
        "scalability_solve_ms_p95.png",
        "scalability_candidate_count.png",
        "scalability_priority_certification_rate.png",
    }
    assert (output / "scalability_generation_ms_p95_data.csv").is_file()
    assert (output / "scalability_candidate_count_data.csv").is_file()
