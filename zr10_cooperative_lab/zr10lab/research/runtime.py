from __future__ import annotations

import time

from ..actions import ActionValidator
from ..models import PolicyContext
from ..recording import dumps
from ..runtime import Experiment


class ResearchExperiment(Experiment):
    """Experiment variant for the virtual search/monitor mission.

    It deliberately bypasses the original multi-station FusionEngine: target
    beliefs come from SearchMonitorMission's controlled virtual perception.
    The Policy/Action/validation/logging contracts stay identical.
    """

    def __init__(self, cfg, recorder, mission, policy=None):
        super().__init__(cfg, recorder, policy=policy)
        self.mission = mission
        self.validator = ActionValidator(cfg)

    def process_research(self, t, dt, states, mission_step, action_transform=None):
        begin = time.perf_counter()
        context = PolicyContext(
            t=float(t), dt=float(dt), step=self.step, devices=states,
            detections=tuple(mission_step.detections), rays=(),
            tracks=tuple(mission_step.tracks), metrics={},
            research=mission_step.policy_payload,
        )
        decision = self.policy.decide(context)
        requested = action_transform(decision.actions) if action_transform else decision.actions
        actions = {}
        for key, action in requested.items():
            try:
                if key != action.device_id:
                    raise ValueError("策略 actions 键与动作 device_id 不一致")
                if key not in states or not states[key].connected:
                    continue
                actions[key] = self.validator.validate(action, states[key], t, dt)
            except (ValueError, KeyError) as exc:
                self.recorder.event("action_rejected", {"device_id": key, "error": str(exc)}, t)
                raise

        # Reuse the platform's standard tables.  Research truth is evaluation-only
        # and never appears in the PolicyContext above.
        self._record(t, states, mission_step.detections, (), mission_step.tracks, (), actions,
                     mission_step.truth_positions)
        self.mission.record(self.recorder, t)
        solver = decision.diagnostics.get("solver") if isinstance(decision.diagnostics, dict) else None
        if isinstance(solver, dict):
            self.recorder.write(
                "research_solver", t,
                method=str(solver.get("method", decision.diagnostics.get("algorithm", "unknown"))),
                status=str(solver.get("status", "unknown")),
                solve_ms=float(solver.get("solve_ms", 0.0)),
                mip_gap=solver.get("mip_gap"),
                level1=solver.get("level1"), level2=solver.get("level2"), level3=solver.get("level3"),
                candidate_count=int(solver.get("candidate_count", 0)),
                timeout=bool(solver.get("timeout", False)),
                extras_json=dumps(solver.get("extras", {})),
            )
        elapsed_ms = (time.perf_counter() - begin) * 1000.0
        diagnostics = {"policy": decision.diagnostics, "research_mission": True}
        self.recorder.write(
            "cycles", t, step=self.step, dt_s=dt, work_ms=elapsed_ms,
            deadline_miss=elapsed_ms > dt * 1000.0,
            detections=len(mission_step.detections), rays=0, localizations=0,
            tracks=len(mission_step.tracks), measured_tracks=sum(bool(x.measured) for x in mission_step.tracks),
            metrics_json=dumps(mission_step.metrics), diagnostics_json=dumps(diagnostics),
        )
        self.latest = {
            "t": t, "step": self.step, "devices": states,
            "tracks": list(mission_step.tracks), "metrics": dict(mission_step.metrics),
            "actions": actions, "detections": list(mission_step.detections),
            "diagnostics": diagnostics,
        }
        self.step += 1
        return actions
