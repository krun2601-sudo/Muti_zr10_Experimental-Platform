from __future__ import annotations

import copy
import json
from pathlib import Path
import time

from ..recording import CSVRecorder
from ..simulation import SimulationWorld
from .mission import SearchMonitorMission
from .paper_policies import build_paper_policy
from .provenance import write_research_provenance
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
    # ResearchExperiment is the single authoritative cadence controller for every
    # method. Keeping cadence outside policies guarantees identical periodic/event
    # decision opportunities in GUI, batch and headless execution.
    if method in ("mappo", "safe_mappo"):
        from .mappo import MAPPOPolicy, SafeMAPPOPolicy
        return MAPPOPolicy(cfg) if method == "mappo" else SafeMAPPOPolicy(cfg)
    return build_paper_policy(method, cfg)


def _policy_builder_name(method: str) -> str:
    if method == "mappo":
        return "zr10lab.research.mappo:MAPPOPolicy"
    if method == "safe_mappo":
        return "zr10lab.research.mappo:SafeMAPPOPolicy"
    return "zr10lab.research.paper_policies:build_paper_policy"


def run_research_simulation(cfg, method="ecprh", output=None, seed=None,
                            realtime=False, progress=None):
    """Run the paper task without physical hardware.

    The virtual SimulationWorld is used only for PTZ execution. SearchMonitorMission
    owns target truth/perception/evaluation, preserving the exact same task semantics
    later used by the hardware-mirror control center. Non-learning methods are
    constructed exclusively through ``build_paper_policy`` so batch, GUI and mirror
    cannot silently drift to different implementations.
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
    run_seed = int(seed if seed is not None else cfg.simulation.get("seed", 7))
    (Path(recorder.path) / "research_run.json").write_text(json.dumps({
        "method": method,
        "seed": run_seed,
        "mission": "search_monitor",
        "completed": completed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    write_research_provenance(recorder.path, cfg=cfg, extra={
        "run_method": str(method), "run_seed": run_seed,
        "environment": "sim", "completed": bool(completed),
        "policy_builder": _policy_builder_name(str(method)),
    })
    return recorder.path
