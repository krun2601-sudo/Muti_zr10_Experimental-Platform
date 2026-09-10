from __future__ import annotations

from dataclasses import dataclass

from .base import CooperativePolicy
from ..types import AETarget, PolicyContext, PolicyDecision


@dataclass(frozen=True, slots=True)
class Step:
    duration_s: float
    azimuth_deg: float
    elevation_deg: float
    label: str


class SynchronizedStepPolicy(CooperativePolicy):
    """Validation policy: every gimbal receives the same step command."""

    name = "synchronized_steps"

    def __init__(self, steps: list[Step], repeat: bool = False) -> None:
        if not steps:
            raise ValueError("At least one step is required")
        self.steps = steps
        self.repeat = repeat
        self.device_ids: tuple[str, ...] = ()
        self.total_duration_s = sum(step.duration_s for step in steps)

    async def initialize(self, device_ids) -> None:
        self.device_ids = tuple(device_ids)

    def compute(self, context: PolicyContext) -> PolicyDecision:
        t = context.elapsed_s
        if self.repeat and self.total_duration_s > 0:
            t %= self.total_duration_s

        cumulative = 0.0
        selected = self.steps[-1]
        selected_index = len(self.steps) - 1
        for index, step in enumerate(self.steps):
            cumulative += step.duration_s
            if t < cumulative:
                selected = step
                selected_index = index
                break

        targets = {
            device_id: AETarget(
                azimuth_deg=selected.azimuth_deg,
                elevation_deg=selected.elevation_deg,
                frame="gimbal_local_ae",
                source=self.name,
            )
            for device_id in self.device_ids
        }
        return PolicyDecision(
            targets=targets,
            phase=selected.label,
            diagnostics={
                "step_index": selected_index,
                "step_count": len(self.steps),
                "common_azimuth_deg": selected.azimuth_deg,
                "common_elevation_deg": selected.elevation_deg,
            },
        )
