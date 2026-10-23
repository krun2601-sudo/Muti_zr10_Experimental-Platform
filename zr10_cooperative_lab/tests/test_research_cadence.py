from __future__ import annotations

from types import SimpleNamespace

from zr10lab.config import load_config
from zr10lab.models import Action, Decision, Track
from zr10lab.research.runtime import ResearchExperiment
from zr10lab.simulation import SimulationWorld


class _Recorder:
    def write(self, *args, **kwargs):
        pass

    def event(self, *args, **kwargs):
        pass


class _Mission:
    def record(self, recorder, t):
        pass


class _CountingPolicy:
    def __init__(self):
        self.calls = 0

    def reset(self):
        pass

    def decide(self, context):
        self.calls += 1
        actions = {
            key: Action(key, yaw_deg=state.yaw_deg, pitch_deg=state.pitch_deg,
                        zoom=state.zoom, issued_t=context.t, ttl_s=0.8,
                        reason="counting")
            for key, state in context.devices.items() if state.connected
        }
        return Decision(actions, {"algorithm": "counting"})


def _step(tracks=()):
    return SimpleNamespace(
        detections=(), tracks=tuple(tracks),
        policy_payload={"mission": "search_monitor", "search": {}, "readiness": {}},
        truth_positions={}, metrics={},
    )


def test_runner_separates_10hz_execution_from_half_second_replanning():
    cfg = load_config("configs/research/search_monitor_base.yaml")
    cfg.policy["research"]["planning"]["replan_period_s"] = 0.5
    cfg.policy["research"]["planning"]["event_replan"] = True
    world = SimulationWorld(cfg)
    policy = _CountingPolicy()
    experiment = ResearchExperiment(cfg, _Recorder(), _Mission(), policy=policy)

    # t=0 plans once. 0.1 and 0.4 only renew the same action lease.
    for t in (0.0, 0.1, 0.4):
        experiment.process_research(t, 0.1, world.states(), _step())
    assert policy.calls == 1
    assert experiment.latest["metrics"]["research_initial_replan_count"] == 1
    assert experiment.latest["metrics"]["research_periodic_replan_count"] == 0

    # The nominal half-second planning boundary produces the second call.
    experiment.process_research(0.5, 0.1, world.states(), _step())
    assert policy.calls == 2
    metrics = experiment.latest["metrics"]
    assert metrics["research_replan_count"] == 2
    assert metrics["research_periodic_replan_count"] == 1
    assert metrics["research_event_replan_count"] == 0
    # The first replan occurs at exactly t=0.0; this must not be treated as a
    # missing timestamp merely because 0.0 is false-y in Python.
    assert metrics["research_replan_frequency_hz"] == 2.0


def test_new_anonymous_track_triggers_off_cycle_replan():
    cfg = load_config("configs/research/search_monitor_base.yaml")
    cfg.policy["research"]["planning"]["replan_period_s"] = 0.5
    cfg.policy["research"]["planning"]["event_replan"] = True
    world = SimulationWorld(cfg)
    policy = _CountingPolicy()
    experiment = ResearchExperiment(cfg, _Recorder(), _Mission(), policy=policy)

    experiment.process_research(0.0, 0.1, world.states(), _step())
    experiment.process_research(0.1, 0.1, world.states(), _step())
    assert policy.calls == 1

    track = Track(
        track_id="vtrack-0001", t=0.2, position=(120.0, 0.0, 60.0),
        velocity=(1.0, 0.0, 0.0),
        covariance=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        last_seen_t=0.2, hits=1, status="confirmed",
        device_ids=(cfg.active_devices[0].id,), measured=True,
    )
    experiment.process_research(0.2, 0.1, world.states(), _step((track,)))
    assert policy.calls == 2
    metrics = experiment.latest["metrics"]
    assert metrics["research_event_replan_count"] == 1
    assert metrics["research_periodic_replan_count"] == 0
