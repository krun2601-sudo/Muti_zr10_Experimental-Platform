from __future__ import annotations

from ..models import Decision
from .optimization import PriorityHorizonMILP
from .policies import ECPRHPolicy, WeightedRHPolicy


def _guaranteed_targets_h1(ps, selected) -> list[str]:
    """Anonymous targets predicted safely visible in the first future slot."""
    if ps.horizon_steps <= 0:
        return []
    result = []
    for j, track_id in enumerate(ps.target_ids):
        if any(bool(p.visibility[j, 0]) for p in selected):
            result.append(track_id)
    return result


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
            "ecprh", diag,
            target_count=len(ps.target_ids),
            overlap_requirements=len(ps.overlap_requirements),
            guaranteed_targets_h1=_guaranteed_targets_h1(ps, selected),
            risk_check_delay_s=float(ps.slot_s),
        ))


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
        }, guaranteed_targets_h1=_guaranteed_targets_h1(ps, selected),
            risk_check_delay_s=float(ps.slot_s)))
