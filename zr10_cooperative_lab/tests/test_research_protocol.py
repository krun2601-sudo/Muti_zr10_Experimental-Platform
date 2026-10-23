from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
import yaml

from zr10lab.config import load_config
from zr10lab.research.paper_policies import _RiskExecutionFactory
from zr10lab.research.protocol import (
    _read_baseline_selections,
    _require_frozen_input_dir,
    load_manifest,
    run_split,
)
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


def test_manifest_pins_baselines_and_test_gate_matches_pretest_learning_decision():
    path = Path("configs/research/paper_experiment_manifest.yaml")
    manifest = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    frozen = manifest["frozen_inputs"]
    assert frozen["baseline_selection_dir"] == "frozen_baselines"
    assert "learning_selection_dir" not in frozen
    directory = path.parent / frozen["baseline_selection_dir"]
    assert directory.is_dir()

    expected = set(manifest["methods"]["parameterized_baselines"])
    hashes = frozen["baseline_selection_sha256"]
    assert set(hashes) == expected
    assert expected.issubset(set(manifest["methods"]["primary"]))
    for method, expected_hash in hashes.items():
        selection = directory / f"selected_{method}.json"
        assert selection.is_file(), method
        actual = hashlib.sha256(selection.read_bytes()).hexdigest()
        assert actual == expected_hash, (method, expected_hash, actual)

    decision = manifest.get("pretest_learning_decision")
    if bool(frozen["paper_test_unlocked"]):
        assert isinstance(decision, dict)
        assert decision.get("main_table") == "omit_optional_learning_baselines"
        assert decision.get("made_before_any_heldout_run") is True
        assert set(manifest["methods"]["primary"]).isdisjoint(
            set(manifest["methods"].get("learning_optional_after_training", [])))
    else:
        assert decision is None or decision.get("main_table") != "omit_optional_learning_baselines"


def test_paper_test_gate_is_locked_or_pretest_omission_is_explicit(tmp_path):
    path = Path("configs/research/paper_experiment_manifest.yaml")
    manifest = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not bool(manifest["frozen_inputs"]["paper_test_unlocked"]):
        baseline_dir = Path("configs/research/frozen_baselines").resolve()
        with pytest.raises(ValueError, match="globally locked"):
            run_split(
                path, "test_main", tmp_path,
                methods=["weighted_rh"], paired=False,
                baseline_selection_dir=baseline_dir,
            )
    else:
        decision = manifest["pretest_learning_decision"]
        assert decision["main_table"] == "omit_optional_learning_baselines"
        assert decision["made_before_any_heldout_run"] is True
        # Do not execute a held-out run in a unit test merely to prove it is unlocked.


def test_non_manifest_baseline_selection_directory_is_rejected_without_running_test(tmp_path):
    manifest_path, manifest = load_manifest("configs/research/paper_experiment_manifest.yaml")
    fake = tmp_path / "replacement"
    fake.mkdir()
    with pytest.raises(ValueError, match="does not match frozen manifest identity"):
        _require_frozen_input_dir(
            manifest_path, manifest, "baseline_selection_dir", fake,
            label="frozen validation selections",
        )


def test_frozen_baseline_hash_mismatch_is_rejected_without_running_test():
    directory = Path("configs/research/frozen_baselines").resolve()
    with pytest.raises(ValueError, match="hash mismatch"):
        _read_baseline_selections(
            directory, ["weighted_rh"],
            expected_sha256={"weighted_rh": "0" * 64},
        )


def test_learning_directory_cannot_be_supplied_before_manifest_freeze(tmp_path):
    manifest_path, manifest = load_manifest("configs/research/paper_experiment_manifest.yaml")
    fake = tmp_path / "candidate_checkpoints"
    fake.mkdir()
    with pytest.raises(ValueError, match="no frozen validation-selected checkpoints"):
        _require_frozen_input_dir(
            manifest_path, manifest, "learning_selection_dir", fake,
            label="validation-selected checkpoints",
        )


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
    factory = _RiskExecutionFactory(ablated)
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


def test_mappo_cost_penalizes_active_but_undiscovered_target():
    cfg = load_config("configs/research/search_monitor_base.yaml")
    cfg.system["duration_s"] = 0.6
    cfg.policy["research"]["perception"]["detection_probability"] = 0.0
    cfg.policy["research"]["scenario"]["targets"] = [{
        "id": "hidden_training_target",
        "start_s": 0.0,
        "end_s": 0.6,
        "trajectory": "cv",
        "position_m": [130.0, 0.0, 60.0],
        "velocity_mps": [0.0, 0.0, 0.0],
    }]
    env = ResearchMARLEnv(cfg, seed=7)
    obs, _ = env.reset(seed=7)
    action = np.zeros((len(cfg.active_devices), 3), dtype=float)
    _, _, _, cost, _, info = env.step(action)
    assert obs.shape[0] == len(cfg.active_devices)
    assert cost > 0.0
    assert info["reward_uses_privileged_truth"] is True
    assert np.isfinite(obs).all()
