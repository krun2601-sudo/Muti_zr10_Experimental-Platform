from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from zr10lab.config import load_config
from zr10lab.research.priority_policies import _ConfigurableExecutionFactory
from zr10lab.research.protocol import run_split
from zr10lab.research.rl_env import ResearchMARLEnv
from zr10lab.research.scalability import benchmark_case
from zr10lab.research.studies import _explicit_yaml_override, apply_override
from zr10lab.simulation import SimulationWorld


def test_frozen_manifest_has_disjoint_scenario_and_seed_splits():
    path = Path("configs/research/paper_experiment_manifest.yaml")
    manifest = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    splits = manifest["splits"]
    seed_sets = {name:set(row["seeds"]) for name,row in splits.items()}
    for name, seeds in seed_sets.items():
        for other, other_seeds in seed_sets.items():
            if name < other:
                assert seeds.isdisjoint(other_seeds), (name, other)
    train = set(splits["train_learning_only"]["scenarios"])
    validation = set(splits["validation_only"]["scenarios"])
    tests = set(splits["test_main"]["scenarios"]) | set(splits["test_ood"]["scenarios"])
    assert train.isdisjoint(validation)
    assert train.isdisjoint(tests)
    assert validation.isdisjoint(tests)


def test_ablation_override_does_not_replace_heldout_scenario():
    scenario = load_config("configs/research/scenarios/S10_heldout_mixed.yaml")
    original = scenario.policy["research"]["scenario"]["id"]
    override = _explicit_yaml_override("configs/research/ablations/no_uncertainty.yaml")
    changed = apply_override(scenario, override)
    assert changed.policy["research"]["scenario"]["id"] == original
    assert changed.policy["research"]["planning"]["use_uncertainty"] is False


def test_no_execution_model_only_changes_planner_assumption():
    cfg = load_config("configs/research/scenarios/S4_boundary_handoff.yaml")
    override = _explicit_yaml_override("configs/research/ablations/no_execution_model.yaml")
    ablated = apply_override(cfg, override)
    world = SimulationWorld(ablated)
    state = world.states()[ablated.active_devices[0].id]
    device = ablated.active_devices[0]
    factory = _ConfigurableExecutionFactory(ablated)
    assert factory.use_execution_model is False
    assert factory._transition_s(state, device, state.yaw_deg + 20.0,
                                 state.pitch_deg, state.zoom) == 0.0
    assert device.max_slew_dps == cfg.active_devices[0].max_slew_dps
    assert ablated.policy["research"]["execution"]["settle_s"] == cfg.policy["research"]["execution"]["settle_s"]


def test_scalability_benchmark_small_case_runs():
    cfg = load_config("configs/research/search_monitor_base.yaml")
    row = benchmark_case(cfg, target_count=1, search_candidates_per_device=1, repetitions=1)
    assert row["candidate_count"] > 0
    assert row["generation_ms_mean"] >= 0
    assert row["solve_ms_mean"] >= 0
    assert row["target_count"] == 1


def test_mappo_training_env_returns_early_on_shared_replan_event():
    cfg = load_config("configs/research/search_monitor_base.yaml")
    cfg.system["duration_s"] = 2.0
    cfg.policy["research"]["planning"]["replan_period_s"] = 0.5
    cfg.policy["research"]["planning"]["event_replan"] = True
    device_id = cfg.active_devices[0].id
    cfg.simulation["outages"] = [{"device_id": device_id, "start_s": 0.2, "end_s": 1.5}]
    env = ResearchMARLEnv(cfg, seed=5)
    obs, _ = env.reset(seed=5)
    assert obs.shape[0] == len(cfg.active_devices)
    action = np.zeros((len(cfg.active_devices), 3), dtype=float)
    _, _, _, _, done, info = env.step(action)
    assert done is False
    assert info["event_triggered"] is True
    assert info["frames_executed"] == 2
    assert info["time_s"] == pytest.approx(0.2)


def test_test_split_refuses_parameterized_baseline_without_validation_selection(tmp_path):
    with pytest.raises(ValueError, match="frozen validation selections"):
        run_split(
            "configs/research/paper_experiment_manifest.yaml",
            "test_main", tmp_path,
            methods=["weighted_rh"], paired=False,
            baseline_selection_dir=None,
        )
