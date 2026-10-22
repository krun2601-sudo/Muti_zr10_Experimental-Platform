from __future__ import annotations

from dataclasses import replace

from ..models import Decision
from .policies import ECPRHPolicy, WeightedRHPolicy


class _ReplanCache:
    def __init__(self, cfg):
        super().__init__(cfg)
        planning = cfg.policy.get("research", {}).get("planning", {})
        self.replan_period_s = float(planning.get("replan_period_s", 0.5))
        if self.replan_period_s <= 0:
            raise ValueError("research.planning.replan_period_s must be positive")
        self._planned_t = -float("inf")
        self._cached_actions = {}
        self._cached_diagnostics = {}

    def reset(self):
        super().reset()
        self._planned_t = -float("inf")
        self._cached_actions = {}
        self._cached_diagnostics = {}

    def _refresh(self, context):
        result = {}
        for key, state in context.devices.items():
            if not state.connected:
                continue
            action = self._cached_actions.get(key)
            if action is None:
                continue
            result[key] = replace(action, issued_t=context.t, ttl_s=self.ttl)
        diag = dict(self._cached_diagnostics)
        diag["cached_plan"] = True
        diag["plan_age_s"] = max(0.0, context.t - self._planned_t)
        # A cached control tick is not a new optimizer invocation; suppress the
        # solver row to avoid counting one solve multiple times in research_solver.csv.
        diag.pop("solver", None)
        return Decision(result, diag)

    def decide(self, context):
        if self._cached_actions and context.t - self._planned_t < self.replan_period_s - 1e-9:
            return self._refresh(context)
        decision = super().decide(context)
        self._planned_t = float(context.t)
        self._cached_actions = dict(decision.actions)
        self._cached_diagnostics = dict(decision.diagnostics)
        decision.diagnostics["cached_plan"] = False
        return decision


class RealtimeECPRHPolicy(_ReplanCache, ECPRHPolicy):
    """ECP-RH at a slower planning rate while the control loop remains fast."""


class RealtimeWeightedRHPolicy(_ReplanCache, WeightedRHPolicy):
    """Weighted RH baseline with exactly the same replanning cadence as ECP-RH."""
