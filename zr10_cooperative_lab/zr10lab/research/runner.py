from __future__ import annotations

import copy
import json
from pathlib import Path
import time

from ..recording import CSVRecorder
from ..simulation import SimulationWorld
from .mission import SearchMonitorMission
from .policies import build_research_policy
from .realtime_policies import RealtimeECPRHPolicy, RealtimeWeightedRHPolicy
from .runtime import ResearchExperiment


def prepare_research_config(cfg, method: str, seed: int | None = None):
    local = copy.deepcopy(cfg)
    local.policy["mission"] = "search_monitor"
    research = local.policy.setdefault("research", {})
    research["method"] = str(method)
    if seed is not None:
        local.simulation["seed"] = int(seed)
        research.setdefault("perception", {})["seed"] = int(seed)
    return local


def _policy(method: str, cfg):
    # RH methods share the same lower replanning rate in both GUI and batch runs.
    if method == "ecprh":
        return RealtimeECPRHPolicy(cfg)
    if method == "weighted_rh":
        return RealtimeWeightedRHPolicy(cfg)
    return build_research_policy(method, cfg)


def run_research_simulation(cfg, method="ecprh", output=None, seed=None,
                            realtime=False, progress=None):
    """Run the paper task without physical hardware.

    The virtual SimulationWorld is used only for PTZ execution. SearchMonitorMission
    owns target truth/perception/evaluation, preserving the exact same task semantics
    later used by the hardware-mirror control center.
    """
    cfg = prepare_research_config(cfg, method, seed)
    world = SimulationWorld(cfg)
    if seed is not None:
        world.reset(seed=int(seed))
    mission = SearchMonitorMission(cfg)
    recorder = CSVRecorder(output or cfg.logging.get("root", "runs"), cfg.to_dict(), "sim")
    policy = _policy(method, cfg)
    experiment = ResearchExperiment(cfg, recorder, mission, policy=policy)
    dt = 1.0 / float(cfg.system.get("rate_hz", 10))
    steps = int(round(float(cfg.system.get("duration_s", 60)) / dt))
    completed = False
    try:
        for _ in range(steps):
            begin = time.perf_counter()
            states = world.states()
            mission_step = mission.step(world.t, dt, states)
            actions = experiment.process_research(world.t, dt, states, mission_step)
            world.advance(actions, dt)
            if progress:
                progress(experiment.latest)
            if realtime:
                time.sleep(max(0.0, dt - (time.perf_counter() - begin)))
        completed = True
    finally:
        recorder.close(completed)
    (Path(recorder.path) / "research_run.json").write_text(json.dumps({
        "method": method,
        "seed": int(seed if seed is not None else cfg.simulation.get("seed", 7)),
        "mission": "search_monitor",
        "completed": completed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return recorder.path
