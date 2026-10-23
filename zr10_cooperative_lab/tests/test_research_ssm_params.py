from pathlib import Path

from zr10lab.config import load_config
from zr10lab.research.paper_policies import build_paper_policy


ROOT = Path(__file__).resolve().parents[1]


def test_ssm_belief_reads_public_tuning_namespace():
    cfg = load_config(ROOT / "configs/research/scenarios/S4_boundary_handoff.yaml")
    params = (
        cfg.policy.setdefault("research", {})
        .setdefault("baselines", {})
        .setdefault("ssm_belief", {})
    )
    params.update({
        "gamma": 0.85,
        "monitor_weight": 2.0,
        "search_weight": 2.0,
        "motion_weight": 0.04,
    })

    policy = build_paper_policy("ssm_belief", cfg)

    assert policy.gamma == 0.85
    assert policy.monitor_weight == 2.0
    assert policy.search_weight == 2.0
    assert policy.motion_weight == 0.04


def test_ssm_belief_parameter_changes_are_not_ignored():
    cfg_a = load_config(ROOT / "configs/research/scenarios/S4_boundary_handoff.yaml")
    cfg_b = load_config(ROOT / "configs/research/scenarios/S4_boundary_handoff.yaml")

    cfg_a.policy.setdefault("research", {}).setdefault("baselines", {})["ssm_belief"] = {
        "gamma": 0.85,
        "monitor_weight": 2.0,
        "search_weight": 0.5,
        "motion_weight": 0.04,
    }
    cfg_b.policy.setdefault("research", {}).setdefault("baselines", {})["ssm_belief"] = {
        "gamma": 0.98,
        "monitor_weight": 8.0,
        "search_weight": 2.0,
        "motion_weight": 0.08,
    }

    policy_a = build_paper_policy("ssm_belief", cfg_a)
    policy_b = build_paper_policy("ssm_belief", cfg_b)

    assert (policy_a.gamma, policy_a.monitor_weight, policy_a.search_weight, policy_a.motion_weight) != (
        policy_b.gamma,
        policy_b.monitor_weight,
        policy_b.search_weight,
        policy_b.motion_weight,
    )
