"""Copy this file when implementing a new cooperative decision algorithm."""

from __future__ import annotations

from .base import CooperativePolicy
from ..types import AETarget, PolicyContext, PolicyDecision


class TemplatePolicy(CooperativePolicy):
    name = "template_policy"

    async def initialize(self, device_ids) -> None:
        self.device_ids = tuple(device_ids)

    def compute(self, context: PolicyContext) -> PolicyDecision:
        # Available inputs:
        #   context.elapsed_s
        #   context.cycle_index
        #   context.device_states[gimbal_id]
        #   context.observations (detections, tracks, estimates, FIM, etc.)
        targets = {}
        for device_id in self.device_ids:
            state = context.device_states[device_id]
            previous = state.last_target
            targets[device_id] = previous or AETarget(
                azimuth_deg=0.0,
                elevation_deg=-10.0,
                frame="gimbal_local_ae",
                source=self.name,
            )

        return PolicyDecision(
            targets=targets,
            phase="hold",
            diagnostics={
                "replace_with_algorithm_metrics": True,
            },
        )
