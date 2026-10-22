from __future__ import annotations

from .policies import (
    ClassicalPTZPolicy,
    FixedScanReactivePolicy,
    InformationPlannerPolicy,
    SSMBeliefPolicy,
)
from .priority_policies import PriorityECPRHPolicy, PriorityWeightedRHPolicy
from .risk_planning import RiskAwarePrimitiveFactory
from .strong_baselines import ExecutionAwareMyopicGreedyPolicy


class _RiskExecutionFactory(RiskAwarePrimitiveFactory):
    """Risk-aware candidate generator with an ablatable planner execution model."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.use_execution_model = bool(
            cfg.policy.get("research", {}).get("planning", {}).get("use_execution_model", True))

    def _transition_s(self, state, device, yaw: float, pitch: float, zoom: float) -> float:
        if not self.use_execution_model:
            return 0.0
        return super()._transition_s(state, device, yaw, pitch, zoom)


class PaperECPRHPolicy(PriorityECPRHPolicy):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.factory = _RiskExecutionFactory(cfg)
        self.ttl = self.factory.ttl_s


class PaperWeightedRHPolicy(PriorityWeightedRHPolicy):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.factory = _RiskExecutionFactory(cfg)
        self.ttl = self.factory.ttl_s


class PaperGreedyPolicy(ExecutionAwareMyopicGreedyPolicy):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.factory = RiskAwarePrimitiveFactory(cfg)
        self.ttl = self.factory.ttl_s


class PaperClassicalPTZPolicy(ClassicalPTZPolicy):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.factory = RiskAwarePrimitiveFactory(cfg)
        self.ttl = self.factory.ttl_s


class PaperInformationPlannerPolicy(InformationPlannerPolicy):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.factory = RiskAwarePrimitiveFactory(cfg)
        self.ttl = self.factory.ttl_s


class PaperSSMBeliefPolicy(SSMBeliefPolicy):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.factory = RiskAwarePrimitiveFactory(cfg)
        self.ttl = self.factory.ttl_s


PAPER_POLICIES = {
    "ecprh": PaperECPRHPolicy,
    "weighted_rh": PaperWeightedRHPolicy,
    "greedy": PaperGreedyPolicy,
    "fixed_scan": FixedScanReactivePolicy,
    "classical_ptz": PaperClassicalPTZPolicy,
    "info_planner": PaperInformationPlannerPolicy,
    "ssm_belief": PaperSSMBeliefPolicy,
}


def build_paper_policy(name: str, cfg):
    """Build the single frozen implementation used by GUI and headless studies."""
    try:
        return PAPER_POLICIES[str(name)](cfg)
    except KeyError as exc:
        raise ValueError(
            f"unknown paper policy {name!r}; choose from {sorted(PAPER_POLICIES)}"
        ) from exc
