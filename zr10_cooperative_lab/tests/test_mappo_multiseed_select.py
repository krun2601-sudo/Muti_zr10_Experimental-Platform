from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from zr10lab.research.candidate_mappo import SELECTION_METRICS
from zr10lab.research.mappo_multiseed_select import aggregate_common_update


def _write_seed(root: Path, network_seed: int, values: dict[int, float], *, drop_case=False):
    train = root / "train"; select = root / "select"
    train.mkdir(parents=True); select.mkdir(parents=True)
    checkpoints = []
    for update in sorted(values):
        checkpoint = train / f"feature_mappo_seed{network_seed}_u{update:04d}.pt"
        checkpoint.write_bytes(f"seed={network_seed};update={update}".encode())
        metadata = {
            "seed": network_seed, "training_update": update,
            "episodes_started": 210, "episode_usage": {f"pair-{i}": 2 for i in range(100)},
        }
        Path(str(checkpoint) + ".json").write_text(json.dumps(metadata), encoding="utf-8")
        checkpoints.append(str(checkpoint))
    index = {
        "implementation": "candidate_feature_v2",
        "seed": network_seed,
        "checkpoints": checkpoints,
    }
    (train / f"feature_mappo_seed{network_seed}_training_index.json").write_text(
        json.dumps(index), encoding="utf-8")

    fields = ["checkpoint", "config", "seed", *SELECTION_METRICS]
    rows = []
    for update, missed in sorted(values.items()):
        for scenario in ("S4_boundary_handoff.yaml", "S8_maneuver.yaml"):
            for validation_seed in (2001, 2002):
                if drop_case and update == max(values) and scenario.startswith("S8") and validation_seed == 2002:
                    continue
                row = {
                    "checkpoint": str(train / f"feature_mappo_seed{network_seed}_u{update:04d}.pt"),
                    "config": scenario, "seed": validation_seed,
                    "research_missed_target_rate": missed,
                    "research_detection_delay_censored_p95_s": 10 + missed,
                    "research_total_loss_s": 20 + missed,
                    "research_max_loss_gap_s": 5 + missed,
                    "research_revisit_age_p95_s": 12 + missed,
                }
                rows.append(row)
    with (select / "validation_checkpoint_runs.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)


def test_selects_one_common_update_across_all_network_seeds(tmp_path):
    # Seed 5101 individually prefers u50; seed 5102 strongly prefers u100. The
    # formal selector must pool both replicas and choose one update for both.
    a = tmp_path / "seed5101"; b = tmp_path / "seed5102"
    _write_seed(a, 5101, {50: 0.00, 100: 0.20})
    _write_seed(b, 5102, {50: 0.80, 100: 0.00})
    result = aggregate_common_update(
        [a, b], tmp_path / "out",
        expected_network_seeds=[5101, 5102],
        expected_validation_seeds=[2001, 2002],
        expected_scenarios=["S4", "S8"],
    )
    assert result["selected_update"] == 100  # pooled missed means: u50=.4, u100=.1
    assert [x["network_seed"] for x in result["replicas"]] == [5101, 5102]
    assert {x["checkpoint"].split("_u")[-1] for x in result["replicas"]} == {"0100.pt"}
    for replica in result["replicas"]:
        data = Path(replica["checkpoint"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == replica["checkpoint_sha256"]


def test_rejects_asymmetric_validation_split(tmp_path):
    a = tmp_path / "seed5101"; b = tmp_path / "seed5102"
    _write_seed(a, 5101, {50: 0.0, 100: 0.0})
    _write_seed(b, 5102, {50: 0.0, 100: 0.0}, drop_case=True)
    with pytest.raises(ValueError, match="validation split differs|expected"):
        aggregate_common_update([a, b], tmp_path / "out")


def test_rejects_different_checkpoint_updates(tmp_path):
    a = tmp_path / "seed5101"; b = tmp_path / "seed5102"
    _write_seed(a, 5101, {50: 0.0, 100: 0.0})
    _write_seed(b, 5102, {50: 0.0, 75: 0.0})
    with pytest.raises(ValueError, match="checkpoint update sets differ"):
        aggregate_common_update([a, b], tmp_path / "out")
