from __future__ import annotations

import json
import hashlib
from pathlib import Path

from zr10lab.research.protocol import _read_baseline_selections


METHODS = ["weighted_rh", "classical_ptz", "info_planner", "ssm_belief"]
EXPECTED = {
    "weighted_rh": {"loss_weight": 100.0, "motion_weight": 0.0, "overlap_weight": 1.0, "search_weight": 1.0},
    "classical_ptz": {"motion_weight": 0.15, "risk_weight": 2.0, "search_weight": 1.0, "track_weight": 4.0},
    "info_planner": {"discovery_weight": 1.0, "motion_weight": 0.02, "track_information_weight": 0.5},
    "ssm_belief": {"gamma": 0.98, "monitor_weight": 2.0, "motion_weight": 0.04, "search_weight": 2.0},
}


def test_archived_geometry_v1_baseline_selections_remain_auditable():
    root = Path("configs/research/frozen_baselines")
    hashes = {
        method: hashlib.sha256((root / f"selected_{method}.json").read_bytes()).hexdigest()
        for method in METHODS
    }
    loaded = _read_baseline_selections(root, METHODS, expected_sha256=hashes)
    assert set(loaded) == set(METHODS)

    for method in METHODS:
        assert loaded[method]["params"] == EXPECTED[method]
        document = json.loads((root / f"selected_{method}.json").read_text(encoding="utf-8"))
        assert document["validation_seeds"] == [2001, 2002, 2003, 2004, 2005]
        assert document["evaluated_parameter_count"] == 24
        assert document["runs_per_parameter_tuple"] == 10
        assert document["provenance"]["workflow_run_id"] == 39903983283
        assert document["provenance"]["data_generation_sha"] == "0bd57b010cce7f512c60022b89a9deb627328421"
        assert document["provenance"]["test_splits_used_for_selection"] is False
        configs = " ".join(document["validation_configs"])
        assert "S4_boundary_handoff" in configs
        assert "S8_maneuver" in configs
        assert "heldout" not in configs.lower()
        assert "S9a_ood" not in configs
        assert "S9b_ood" not in configs
        assert "S7_overload" not in configs
        assert len(document["provenance"]["artifacts"]) == 5
        assert {row["seed"] for row in document["provenance"]["artifacts"]} == {2001, 2002, 2003, 2004, 2005}
