from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import numpy as np
import pytest

from zr10lab.actions import ActionValidator
from zr10lab.config import load_config
from zr10lab.coverage import CoverageConfigurationError, CoverageProblem, CoverageTracker
from zr10lab.geometry import intrinsics_at_zoom, project_world_points
from zr10lab.models import CoverageSnapshot, PolicyContext, Telemetry
from zr10lab.runtime import run_simulation
from zr10lab.algorithms.coverage_base import verify_routes
from zr10lab.algorithms.fixed_sweep import FixedSweepPolicy
from zr10lab.algorithms.equal_workload import EqualWorkloadPolicy
from zr10lab.algorithms.cooperative_greedy import CooperativeGreedyPolicy
from zr10lab.algorithms.time_aware_partition import TimeAwarePartitionPolicy
from zr10lab.algorithms.viewpoint_local_search import ViewpointLocalSearchPolicy
from zr10lab.algorithms.optimal_reference import OptimalReferencePolicy

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "configs" / "coverage_smoke.yaml"


def _cfg():
    return load_config(SMOKE)


def _states(cfg, problem, t=0.0):
    return {d.id: Telemetry(d.id, t, d.initial_yaw_deg, d.initial_pitch_deg,
                            zoom=problem.fixed_zoom, source="simulation")
            for d in cfg.active_devices}


def _context(cfg, problem):
    return PolicyContext(0.0, .1, 0, _states(cfg, problem),
                         coverage=CoverageSnapshot(problem_hash=problem.problem_hash,
                                                   visited_mask=tuple(False for _ in problem.cell_ids)))


def test_problem_hash_and_coverage_matrix_uses_project_world_points():
    cfg = _cfg(); p1 = CoverageProblem(cfg); p2 = CoverageProblem(cfg)
    p1.assert_feasible()
    assert p1.problem_hash == p2.problem_hash
    assert len(p1.cells_m) == 18
    for did in p1.device_ids:
        d = p1.devices[did]
        for vp in p1.viewpoints_by_device[did][:2]:
            state = Telemetry(did, 0.0, vp.yaw_deg, vp.pitch_deg, zoom=vp.zoom, source="simulation")
            intr = intrinsics_at_zoom(d, vp.zoom)
            projected = project_world_points(p1.cells_m, state, d)
            for m in vp.covered_cell_ids:
                assert projected[m] is not None
                u, v = projected[m]
                assert p1.fov_margin * intr.width <= u <= (1 - p1.fov_margin) * intr.width
                assert p1.fov_margin * intr.height <= v <= (1 - p1.fov_margin) * intr.height


def test_tracker_does_not_cover_while_moving_or_before_dwell():
    cfg = _cfg(); p = CoverageProblem(cfg); tracker = CoverageTracker(p)
    did = p.device_ids[0]; vp = p.viewpoints_by_device[did][0]
    others = _states(cfg, p)
    moving = Telemetry(did, 0.0, vp.yaw_deg, vp.pitch_deg, zoom=p.fixed_zoom,
                       yaw_rate_dps=5.0, source="simulation")
    states = dict(others); states[did] = moving
    snap = tracker.update(0.0, states)
    assert not snap.newly_covered_ids
    still = Telemetry(did, .1, vp.yaw_deg, vp.pitch_deg, zoom=p.fixed_zoom, source="simulation")
    states[did] = still; tracker.update(.1, states)
    states[did] = Telemetry(did, .29, vp.yaw_deg, vp.pitch_deg, zoom=p.fixed_zoom, source="simulation")
    assert not tracker.update(.29, states).newly_covered_ids
    states[did] = Telemetry(did, .31, vp.yaw_deg, vp.pitch_deg, zoom=p.fixed_zoom, source="simulation")
    assert tracker.update(.31, states).newly_covered_ids


@pytest.mark.parametrize("policy_cls", [
    FixedSweepPolicy, EqualWorkloadPolicy, CooperativeGreedyPolicy,
    TimeAwarePartitionPolicy, ViewpointLocalSearchPolicy, OptimalReferencePolicy,
])
def test_all_baselines_plan_shared_feasible_problem_and_actions_validate(policy_cls):
    cfg = _cfg(); policy = policy_cls(cfg); p = policy.problem
    context = _context(cfg, p)
    plan = policy.plan_routes(context)
    verify_routes(p, plan.routes)
    assert p.route_makespan(plan.routes) <= sum(p.route_cost(d, plan.routes.get(d, ())) for d in p.device_ids) + 1e-12
    decision = policy.decide(context)
    validator = ActionValidator(cfg)
    for did, action in decision.actions.items():
        validator.validate(action, context.devices[did], context.t, context.dt)
        assert action.reason.startswith(policy.algorithm_id + ":")


def test_algorithms_do_not_import_runtime_hardware_simulation_or_truth():
    directory = ROOT / "zr10lab" / "algorithms"
    forbidden_modules = ("zr10lab.simulation", "zr10lab.hardware", "zr10lab.runtime", "zr10lab.vision")
    for path in directory.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith(forbidden_modules) for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(forbidden_modules)
            if isinstance(node, ast.Attribute):
                assert node.attr != "truth"


def test_unreachable_cells_fail_before_run():
    cfg = _cfg()
    cfg.policy["coverage"]["effective_range_m"] = 1.0
    p = CoverageProblem(cfg)
    with pytest.raises(CoverageConfigurationError, match="不可达"):
        p.assert_feasible()


def test_small_simulation_completes_and_logs_consistently(tmp_path):
    cfg = _cfg()
    cfg.policy.update(name="custom", custom="zr10lab.algorithms.cooperative_greedy:CooperativeGreedyPolicy",
                      algorithm_id="cg")
    session = Path(run_simulation(cfg, tmp_path))
    metadata = json.loads((session / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["completed"] is True
    assert metadata["problem_hash"]
    with (session / "coverage_cells.csv").open(encoding="utf-8-sig", newline="") as f:
        cells = list(csv.DictReader(f))
    assert len(cells) == 18
    first = [float(r["first_covered_t_s"]) for r in cells]
    assert max(first) == pytest.approx(float(metadata["coverage_completion_time_s"]))
    with (session / "cycles.csv").open(encoding="utf-8-sig", newline="") as f:
        cycles = list(csv.DictReader(f))
    metrics = json.loads(cycles[-1]["metrics_json"])
    diagnostics = json.loads(cycles[-1]["diagnostics_json"])
    assert metrics["coverage_complete"] is True
    assert metrics["coverage_fraction"] == pytest.approx(1.0)
    assert diagnostics["policy"]["done"] is True
    assert diagnostics["policy"]["problem_hash"] == metadata["problem_hash"]
