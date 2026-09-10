from __future__ import annotations

from ..config import PolicyConfig
from .base import CooperativePolicy
from .synchronized_steps import Step, SynchronizedStepPolicy


def build_policy(config: PolicyConfig) -> CooperativePolicy:
    if config.type == "synchronized_steps":
        steps = [
            Step(
                duration_s=float(item["duration_s"]),
                azimuth_deg=float(item["azimuth_deg"]),
                elevation_deg=float(item["elevation_deg"]),
                label=str(item.get("label", f"step_{index}")),
            )
            for index, item in enumerate(config.steps)
        ]
        return SynchronizedStepPolicy(steps=steps, repeat=config.repeat)

    raise ValueError(
        f"Unknown policy type {config.type!r}. Add it in zr10_coop/policies/factory.py"
    )
