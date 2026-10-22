from __future__ import annotations

from collections import Counter
from dataclasses import replace
import time

from ..actions import ActionValidator
from ..models import Decision, PolicyContext
from ..recording import dumps
from ..runtime import Experiment
from .execution import ExecutionEvaluator


class ResearchExperiment(Experiment):
    """Experiment variant for the virtual search/monitor mission."""

    def __init__(self, cfg, recorder, mission, policy=None):
        super().__init__(cfg, recorder, policy=policy)
        self.mission = mission
        self.validator = ActionValidator(cfg)
        self.execution = ExecutionEvaluator()
        planning = cfg.policy.get("research", {}).get("planning", {})
        self.replan_period_s = float(planning.get("replan_period_s", 0.5))
        self.event_replan = bool(planning.get("event_replan", True))
        if self.replan_period_s <= 0:
            raise ValueError("research planning.replan_period_s must be positive")
        self._last_plan_t = -float("inf")
        self._last_event_signature = None
        self._cached_policy_actions = {}
        self._cached_policy_diagnostics = {}
        self._policy_identity = id(self.policy)
        self._replan_counts = Counter()
        self._first_replan_t: float | None = None
        self._last_replan_t: float | None = None

    @staticmethod
    def _event_signature(context: PolicyContext):
        """Only discrete information changes trigger an off-cycle replan."""
        tracks = tuple(sorted(
            (tr.track_id, tr.status, tuple(sorted(set(tr.device_ids))))
            for tr in context.tracks
        ))
        devices = tuple(sorted((key, bool(value.connected)) for key, value in context.devices.items()))
        return tracks, devices

    def _invalidate_policy_internal_cache(self) -> None:
        invalidate = getattr(self.policy, "invalidate_plan", None)
        if callable(invalidate):
            invalidate()
            return
        if hasattr(self.policy, "last_t") and hasattr(self.policy, "cached"):
            try:
                self.policy.last_t = -float("inf")
                self.policy.cached = {}
            except Exception:
                pass

    def _register_replan(self, t: float, reason: str) -> None:
        self._replan_counts[reason] += 1
        self._replan_counts["total"] += 1
        if self._first_replan_t is None:
            self._first_replan_t = float(t)
        self._last_replan_t = float(t)

    def _replan_metrics(self, t: float) -> dict[str, float | int]:
        elapsed = max(0.0, float(t) - float(self._first_replan_t or t))
        count = int(self._replan_counts["total"])
        # Exclude the first immediate plan from the empirical frequency numerator;
        # otherwise very short smoke tests report an artificial high rate.
        frequency = max(count - 1, 0) / elapsed if elapsed > 1e-12 else 0.0
        return {
            "research_replan_count": count,
            "research_initial_replan_count": int(self._replan_counts["initial"]),
            "research_periodic_replan_count": int(self._replan_counts["periodic"]),
            "research_event_replan_count": int(self._replan_counts["event"]),
            "research_replan_frequency_hz": float(frequency),
        }

    def _decide(self, context: PolicyContext) -> tuple[Decision, bool, str, float]:
        if id(self.policy) != self._policy_identity:
            self._policy_identity = id(self.policy)
            self._cached_policy_actions = {}
            self._cached_policy_diagnostics = {}
            self._last_plan_t = -float("inf")
            self._last_event_signature = None

        signature = self._event_signature(context)
        initial = not self._cached_policy_actions
        periodic = context.t - self._last_plan_t >= self.replan_period_s - 1e-12
        event = self.event_replan and self._last_event_signature is not None and signature != self._last_event_signature
        replan = initial or periodic or event
        if replan:
            if event:
                self._invalidate_policy_internal_cache()
            started = time.perf_counter()
            decision = self.policy.decide(context)
            compute_ms = (time.perf_counter() - started) * 1000.0
            self._cached_policy_actions = dict(decision.actions)
            self._cached_policy_diagnostics = dict(decision.diagnostics or {})
            self._last_plan_t = float(context.t)
            self._last_event_signature = signature
            reason = "initial" if initial else "event" if event else "periodic"
            self._register_replan(context.t, reason)
            diagnostics = dict(self._cached_policy_diagnostics)
            diagnostics.update(cached_plan=False, replan_reason=reason,
                               decision_compute_ms=compute_ms, plan_age_s=0.0)
            return Decision(dict(decision.actions), diagnostics), True, reason, compute_ms

        actions = {key: replace(action, issued_t=context.t)
                   for key, action in self._cached_policy_actions.items()}
        diagnostics = dict(self._cached_policy_diagnostics)
        diagnostics.update(cached_plan=True, replan_reason="cached",
                           decision_compute_ms=0.0,
                           plan_age_s=max(0.0, float(context.t) - self._last_plan_t))
        return Decision(actions, diagnostics), False, "cached", 0.0

    def process_research(self, t, dt, states, mission_step, action_transform=None):
        begin = time.perf_counter()
        context = PolicyContext(
            t=float(t), dt=float(dt), step=self.step, devices=states,
            detections=tuple(mission_step.detections), rays=(),
            tracks=tuple(mission_step.tracks), metrics={},
            research=mission_step.policy_payload,
        )
        decision, replanned, replan_reason, decision_compute_ms = self._decide(context)

        if replanned and isinstance(decision.diagnostics, dict):
            guaranteed = decision.diagnostics.get("guaranteed_targets_h1")
            delay = decision.diagnostics.get("risk_check_delay_s")
            if guaranteed is not None and delay is not None:
                self.mission.evaluator.register_risk_prediction(
                    float(t) + max(0.0, float(delay)), guaranteed)

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

        execution = self.execution.update(
            dt, states, getattr(self.mission, "last_readiness", {}), actions, replanned)
        mission_step.metrics.update(execution.metrics())
        mission_step.metrics.update(self._replan_metrics(t))

        self._record(t, states, mission_step.detections, (), mission_step.tracks, (), actions,
                     mission_step.truth_positions)
        self.mission.record(self.recorder, t)
        solver = decision.diagnostics.get("solver") if isinstance(decision.diagnostics, dict) else None
        if replanned and isinstance(solver, dict):
            self.recorder.write(
                "research_solver", t,
                method=str(solver.get("method", decision.diagnostics.get("algorithm", "unknown"))),
                status=str(solver.get("status", "unknown")),
                solve_ms=float(solver.get("solve_ms", 0.0)),
                mip_gap=solver.get("mip_gap"),
                level1=solver.get("level1"), level2=solver.get("level2"), level3=solver.get("level3"),
                candidate_count=int(solver.get("candidate_count", 0)),
                timeout=bool(solver.get("timeout", False)),
                extras_json=dumps({**solver.get("extras", {}), "replan_reason": replan_reason,
                                   "decision_compute_ms": decision_compute_ms}),
            )
        elapsed_ms = (time.perf_counter() - begin) * 1000.0
        diagnostics = {"policy": decision.diagnostics, "research_mission": True,
                       "replanned": replanned, "replan_reason": replan_reason,
                       "decision_compute_ms": decision_compute_ms,
                       "execution": execution.metrics(),
                       "replanning": self._replan_metrics(t)}
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
