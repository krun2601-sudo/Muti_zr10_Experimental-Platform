from __future__ import annotations

import copy
import csv
from pathlib import Path

import numpy as np
import pytest

from zr10lab.config import load_config
from zr10lab.models import PolicyContext, Telemetry
from zr10lab.research.control_center import ResearchControlCenter
from zr10lab.research.perception import VirtualPerception
from zr10lab.research.planning import HorizonMILP, Primitive, PrimitiveFactory, PrimitiveSet
from zr10lab.research.rl_env import ResearchObservationEncoder
from zr10lab.research.runner import run_research_simulation
from zr10lab.research.search_map import ReadinessTracker
from zr10lab.research.types import DeviceReadiness, TruthTarget
from zr10lab.geometry import world_to_gimbal_angles


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs" / "research" / "search_monitor_base.yaml"


def cfg():
    return load_config(BASE)


def test_research_config_loads_and_legacy_sim_targets_are_cleared():
    c = cfg()
    assert c.policy["mission"] == "search_monitor"
    assert c.simulation["targets"] == []
    assert len(c.active_devices) == 4
    assert c.action_space["enabled"] == ["yaw_deg", "pitch_deg", "zoom"]


def test_readiness_requires_settling_and_resets_on_motion():
    c = cfg()
    tracker = ReadinessTracker(c)
    state = Telemetry("zr10_25", 0.0, 0.0, 0.0, zoom=1.0, connected=True)
    first = tracker.update(0.0, {"zr10_25": state})["zr10_25"]
    assert not first.sensing_valid and first.reason == "settling"
    ready = tracker.update(0.30, {"zr10_25": state})["zr10_25"]
    assert ready.sensing_valid
    moving = Telemetry("zr10_25", 0.31, 1.0, 0.0, zoom=1.0,
                       yaw_rate_dps=5.0, connected=True)
    result = tracker.update(0.31, {"zr10_25": moving})["zr10_25"]
    assert not result.sensing_valid and result.reason == "moving_or_zooming"


def test_virtual_perception_exposes_anonymous_track_not_truth_id():
    c = cfg()
    c.policy["research"]["perception"]["detection_probability"] = 1.0
    perception = VirtualPerception(c)
    device = c.active_devices[0]
    target = TruthTarget("private-secret-target", 1.0, (120.0, -25.0, 58.0), (1.0, 0.0, 0.0))
    yaw, pitch = world_to_gimbal_angles(target.position, device)
    states = {device.id: Telemetry(device.id, 1.0, yaw, pitch, zoom=1.0, connected=True)}
    readiness = {device.id: DeviceReadiness(device.id, True, 0.0, "ready")}
    snap = perception.step(1.0, {target.truth_id: target}, states, readiness)
    assert len(snap.tracks) == 1
    assert snap.tracks[0].track_id.startswith("vtrack-")
    assert target.truth_id not in repr(snap.tracks[0])
    assert all(target.truth_id not in repr(d) for d in snap.detections)
    # The mapping exists only behind an explicit private evaluation hook.
    assert perception.private_truth_to_track()[target.truth_id] == snap.tracks[0].track_id


def test_hold_primitive_respects_not_ready_sensor():
    c = cfg()
    factory = PrimitiveFactory(c)
    device = c.active_devices[0]
    state = Telemetry(device.id, 0.0, device.initial_yaw_deg, device.initial_pitch_deg,
                      zoom=device.initial_zoom, connected=True)
    search = {"positions_m": np.asarray([[120.0, 0.0, 60.0]]),
              "ages_s": np.asarray([10.0]), "observed_now": np.asarray([0])}
    context = PolicyContext(0.0, 0.1, 0, {device.id: state}, research={
        "mission": "search_monitor", "search": search,
        "readiness": {device.id: {"sensing_valid": False, "stable_since": None,
                                   "reason": "moving_or_zooming"}},
    })
    ps = factory.generate(context)
    hold = next(p for p in ps.by_device[device.id] if p.kind == "hold")
    assert hold.ready_slot >= 1
    assert hold.transition_s >= c.policy["research"]["execution"]["settle_s"]


def _primitive(index, kind, visibility, search, cost=0.0):
    return Primitive(index=index, device_id="cam", kind=kind,
                     yaw_deg=0.0, pitch_deg=0.0, zoom=1.0, target_ids=(),
                     transition_s=0.0, ready_slot=0,
                     visibility=np.asarray(visibility, dtype=bool),
                     search_coverage=np.asarray(search, dtype=bool), execution_cost=cost)


def test_lexicographic_level1_cannot_trade_loss_for_search():
    # One camera must choose either target continuity OR fresh-area search.
    keep = _primitive(0, "track", [[1]], [[0]], 1.0)
    search = _primitive(1, "search", [[0]], [[1]], 0.0)
    ps = PrimitiveSet(by_device={"cam": (keep, search)}, flat=(keep, search),
                      target_ids=("track",), search_positions=np.asarray([[1.0, 0.0, 0.0]]),
                      search_ages_s=np.asarray([100.0]), horizon_steps=1, slot_s=1.0,
                      overlap_requirements=())
    problem = HorizonMILP(ps, time_limit_s=2.0, mip_rel_gap=0.0)
    selected, lex = problem.solve_lexicographic()
    assert lex.level1 == pytest.approx(0.0, abs=1e-7)
    assert selected[0].kind == "track"
    # Deliberately low finite loss weight and high search reward make weighted MPC
    # accept a visibility loss; this is the exact trade-off ECP-RH eliminates.
    weighted_selected, weighted = problem.solve_weighted(loss_weight=0.01, search_weight=100.0,
                                                          motion_weight=0.0)
    assert weighted.level1 is not None and weighted.level1 >= lex.level1 - 1e-8
    assert weighted_selected[0].kind == "search"


def test_rl_observation_has_fixed_shape_and_no_private_truth_field():
    c = cfg()
    encoder = ResearchObservationEncoder(c, max_targets=3, top_search_cells=4)
    states = {d.id: Telemetry(d.id, 0.0, d.initial_yaw_deg, d.initial_pitch_deg,
                              zoom=d.initial_zoom, connected=True) for d in c.active_devices}
    context = PolicyContext(0.0, 0.1, 0, states, tracks=(), research={
        "mission": "search_monitor",
        "search": {"positions_m": np.asarray([[120.0, 0.0, 60.0]]),
                   "ages_s": np.asarray([10.0]), "observed_now": np.asarray([0])},
        "readiness": {d.id: {"sensing_valid": True} for d in c.active_devices},
    })
    observation = encoder.encode(context)
    assert observation.shape == (4, encoder.obs_dim)
    assert np.isfinite(observation).all()
    assert "truth" not in context.research


def test_short_headless_run_writes_research_tables(tmp_path):
    c = cfg()
    c.system["duration_s"] = 0.6
    c.policy["research"]["scenario"]["targets"] = []
    c.logging["root"] = str(tmp_path)
    path = run_research_simulation(c, method="fixed_scan", output=tmp_path, seed=11)
    path = Path(path)
    assert (path / "metadata.json").exists()
    assert (path / "research_search.csv").exists()
    with (path / "research_search.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows
    assert float(rows[-1]["max_age_s"]) >= 0.0


def test_mirror_requires_explicit_arm_without_touching_hardware():
    c = cfg()
    with pytest.raises(ValueError, match="--arm"):
        ResearchControlCenter(c, environment="mirror", armed=False)
    center = ResearchControlCenter(c, environment="mirror", armed=True)
    try:
        snapshot = center.snapshot()
        assert snapshot["environment"] == "sim"
        assert snapshot["research_environment"] == "mirror"
        assert snapshot["mirror_hardware"] is True
    finally:
        center.close()
