from __future__ import annotations

from ..models import Decision
from .optimization import PriorityHorizonMILP
from .policies import ECPRHPolicy, WeightedRHPolicy


class PriorityECPRHPolicy(ECPRHPolicy):
    """ECP-RH implementation using the always-feasible soft-overlap MILP."""

    def decide(self, context):
        self._check(context)
        ps = self.factory.generate(context)
        if not ps.flat:
            return Decision(self._holds(context, "ecprh_no_candidate"),
                            self._diag("ecprh", candidate_count=0))
        solver = PriorityHorizonMILP(ps, self.time_limit_s, self.mip_gap)
        selected, diag = solver.solve_lexicographic("ecprh")
        actions = (self._actions(context, selected, "ecprh") if selected
                   else self._holds(context, "ecprh_solver_fallback"))
        return Decision(actions, self._diag(
            "ecprh", diag, target_count=len(ps.target_ids),
            overlap_requirements=len(ps.overlap_requirements)))


class PriorityWeightedRHPolicy(WeightedRHPolicy):
    """Same-model finite-weight RH-MPC baseline with soft overlap variables."""

    def __init__(self, cfg):
        super().__init__(cfg)
        weights = cfg.policy.get("research", {}).get("baselines", {}).get("weighted_rh", {})
        self.overlap_weight = float(weights.get("overlap_weight", 3.0))

    def decide(self, context):
        self._check(context)
        ps = self.factory.generate(context)
        if not ps.flat:
            return Decision(self._holds(context, "weighted_no_candidate"), self._diag("weighted_rh"))
        solver = PriorityHorizonMILP(ps, self.time_limit_s, self.mip_gap)
        selected, diag = solver.solve_weighted(
            self.loss_weight, self.overlap_weight,
            self.search_weight, self.motion_weight,
            method="weighted_rh",
        )
        actions = (self._actions(context, selected, "weighted_rh") if selected
                   else self._holds(context, "weighted_solver_fallback"))
        return Decision(actions, self._diag("weighted_rh", diag, weights={
            "loss": self.loss_weight, "overlap": self.overlap_weight,
            "search": self.search_weight, "motion": self.motion_weight,
        }))
