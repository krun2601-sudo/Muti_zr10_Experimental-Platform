from __future__ import annotations

import math

import numpy as np
import pytest

from zr10lab.config import DeviceConfig, load_config
from zr10lab.control_modes import create_mode_policy
from zr10lab.models import Action, Telemetry
from zr10lab.research.evaluation import ResearchEvaluator
from zr10lab.research.execution import ExecutionEvaluator
from zr10lab.research.optimization import PriorityHorizonMILP
from zr10lab.research.paper_policies import build_paper_policy
from zr10lab.research.planning import Primitive, PrimitiveSet
from zr10lab.research.risk_planning import RiskAwarePrimitiveFactory
from zr10lab.research.types import DeviceReadiness, ResearchTargetStatus


def _primitive(index, visible):
    return Primitive(
        index=index, device_id="cam", kind="track" if visible else "hold",
        yaw_deg=0.0, pitch_deg=0.0, zoom=1.0,
        target_ids=("vtrack-0001",) if visible else (),
        transition_s=0.0, ready_slot=0,
        visibility=np.asarray([[visible]], dtype=bool),
        search_coverage=np.empty((0, 1), dtype=bool),
        execution_cost=0.0,
    )


def test_soft_overlap_cannot_make_overloaded_problem_infeasible():
    # One device can keep the target visible, but a two-camera handover overlap is
    # physically impossible. The optimizer must keep the target and report partial
    # overlap satisfaction instead of returning infeasible.
    keep = _primitive(0, True)
    hold = _primitive(1, False)
    ps = PrimitiveSet(
        by_device={"cam": (keep, hold)}, flat=(keep, hold),
        target_ids=("vtrack-0001",),
        search_positions=np.empty((0, 3)), search_ages_s=np.empty((0,)),
        horizon_steps=1, slot_s=1.0,
        overlap_requirements=((0, 0, 2.0),),
    )
    solver = PriorityHorizonMILP(ps, time_limit_s=2.0, mip_rel_gap=0.0)
    selected, diag = solver.solve_lexicographic()
    assert selected and selected[0].index == keep.index
    assert diag.level1 == pytest.approx(0.0, abs=1e-6)
    assert diag.overlap_shortfall == pytest.approx(0.5, abs=1e-6)
    assert diag.extras["overlap_satisfaction_fraction"] == pytest.approx(0.5, abs=1e-6)
    assert diag.extras["visibility_level_certified"] is True
    assert diag.extras["priority_certified"] is True
    assert "infeasible" not in diag.status


def test_axiswise_angular_covariance_jacobian_matches_simple_geometry():
    device = DeviceConfig(id="cam", position_m=(0.0, 0.0, 0.0),
                          mount_rpy_deg=(0.0, 0.0, 0.0))
    sigma_yaw, sigma_pitch = RiskAwarePrimitiveFactory.angular_std_deg(
        np.asarray([100.0, 0.0, 0.0]), np.eye(3), device)
    expected = math.degrees(0.01)
    assert sigma_yaw == pytest.approx(expected, rel=1e-8)
    assert sigma_pitch == pytest.approx(expected, rel=1e-8)


def test_smaller_visibility_risk_produces_larger_gaussian_margin():
    strict = load_config("configs/research/search_monitor_base.yaml")
    loose = load_config("configs/research/search_monitor_base.yaml")
    strict.policy["research"]["planning"]["visibility_risk"] = 0.01
    loose.policy["research"]["planning"]["visibility_risk"] = 0.20
    f_strict = RiskAwarePrimitiveFactory(strict)
    f_loose = RiskAwarePrimitiveFactory(loose)
    assert f_strict._risk_multiplier(3) > f_loose._risk_multiplier(3) > 0.0


def test_headless_and_control_center_build_same_frozen_ecprh_class():
    cfg = load_config("configs/research/search_monitor_base.yaml")
    headless = build_paper_policy("ecprh", cfg)
    gui = create_mode_policy(cfg, "ecprh", reload=False)
    assert type(headless).__module__ == type(gui).__module__ == "zr10lab.research.paper_policies"
    assert type(headless).__name__ == type(gui).__name__ == "PaperECPRHPolicy"
    assert type(headless.factory).__name__ == type(gui.factory).__name__ == "_RiskExecutionFactory"


def test_empirical_risk_prediction_counts_only_due_active_targets():
    evaluator = ResearchEvaluator()
    evaluator.register_risk_prediction(1.0, ["vtrack-0001"])
    status = ResearchTargetStatus(
        truth_id="private", track_id="vtrack-0001", active=True,
        discovered=True, visible_devices=(), sensing_devices=(),
        discovery_t=0.0, current_loss_gap_s=0.0, longest_loss_gap_s=0.0,
    )
    before = evaluator.update(0.5, 0.1, (status,), None)
    assert before["research_risk_prediction_trials"] == 0
    after = evaluator.update(1.0, 0.1, (status,), None)
    assert after["research_risk_prediction_trials"] == 1
    assert after["research_risk_prediction_violations"] == 1
    assert after["research_empirical_risk_violation_rate"] == pytest.approx(1.0)


def test_undiscovered_target_is_explicit_failure_not_zero_loss_success():
    evaluator = ResearchEvaluator()
    unseen = ResearchTargetStatus(
        truth_id="private-missed", track_id=None, active=True,
        discovered=False, visible_devices=(), sensing_devices=(),
        discovery_t=None, current_loss_gap_s=0.0, longest_loss_gap_s=0.0,
    )
    evaluator.update(0.0, 0.1, (unseen,), None)
    metrics = evaluator.update(2.0, 0.1, (unseen,), None)
    assert metrics["research_total_loss_s"] == pytest.approx(0.0)
    assert metrics["research_missed_target_count"] == 1
    assert metrics["research_missed_target_rate"] == pytest.approx(1.0)
    assert metrics["research_discovery_rate"] == pytest.approx(0.0)
    assert metrics["research_detection_delay_censored_p95_s"] == pytest.approx(2.0)


def test_execution_metrics_use_actual_virtual_feedback_not_requested_jump():
    evaluator = ExecutionEvaluator()
    ready = {"cam": DeviceReadiness("cam", True, 0.0, "ready")}
    s0 = {"cam": Telemetry("cam", 0.0, 0.0, 0.0, zoom=1.0, connected=True)}
    a0 = {"cam": Action("cam", yaw_deg=90.0, pitch_deg=10.0, zoom=5.0,
                         target_ids=("vtrack-0001",), reason="ecprh_track")}
    first = evaluator.update(0.1, s0, ready, a0, replanned=True)
    assert first.total_yaw_motion_deg == pytest.approx(0.0)
    assert first.total_zoom_change == pytest.approx(0.0)

    s1 = {"cam": Telemetry("cam", 0.1, 3.0, 1.0, zoom=1.3,
                            yaw_rate_dps=30.0, pitch_rate_dps=10.0, connected=True)}
    moving = {"cam": DeviceReadiness("cam", False, None, "moving_or_zooming")}
    second = evaluator.update(0.1, s1, moving, a0, replanned=False)
    assert second.total_yaw_motion_deg == pytest.approx(3.0)
    assert second.total_pitch_motion_deg == pytest.approx(1.0)
    assert second.total_zoom_change == pytest.approx(0.3)
    assert second.moving_device_s == pytest.approx(0.1)
