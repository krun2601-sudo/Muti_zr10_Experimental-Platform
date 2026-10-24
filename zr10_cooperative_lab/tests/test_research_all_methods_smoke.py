from __future__ import annotations

import csv
from pathlib import Path

import pytest

from zr10lab.config import load_config
from zr10lab.research.batch import DEFAULT_METHODS
from zr10lab.research.runner import run_research_simulation


@pytest.mark.parametrize("method", DEFAULT_METHODS)
def test_primary_nonlearning_method_completes_common_headless_loop(tmp_path, method):
    cfg = load_config("configs/research/search_monitor_base.yaml")
    cfg.system["duration_s"] = 0.8
    cfg.policy["research"]["planning"]["horizon_s"] = 1.0
    cfg.policy["research"]["planning"]["slot_s"] = 0.5
    cfg.policy["research"]["planning"]["search_candidates_per_device"] = 2
    cfg.policy["research"]["planning"]["solver_time_limit_s"] = 0.5
    cfg.policy["research"]["scenario"]["targets"] = [{
        "id": "private_smoke_target",
        "start_s": 0.0,
        "end_s": 0.8,
        "trajectory": "cv",
        "position_m": [25.0, 0.0, 35.0],
        "velocity_mps": [0.5, 0.1, 0.0],
    }]
    run_dir = Path(run_research_simulation(cfg, method, tmp_path / method, seed=123))
    assert (run_dir / "metadata.json").is_file()
    assert (run_dir / "research_run.json").is_file()
    assert (run_dir / "cycles.csv").is_file()
    with (run_dir / "cycles.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows
    assert len(rows) == round(cfg.system["duration_s"] * cfg.system["rate_hz"])
    assert (run_dir / "actions.csv").stat().st_size > 0
