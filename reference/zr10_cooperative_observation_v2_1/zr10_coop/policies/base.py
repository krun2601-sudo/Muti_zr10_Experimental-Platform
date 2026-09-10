from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from ..types import PolicyContext, PolicyDecision


class CooperativePolicy(ABC):
    """Stable interface between high-level decision algorithms and hardware."""

    name = "base_policy"

    async def initialize(self, device_ids: Sequence[str]) -> None:
        return None

    @abstractmethod
    def compute(self, context: PolicyContext) -> PolicyDecision:
        """Return one target AE command for every controlled gimbal."""
        raise NotImplementedError

    async def close(self) -> None:
        return None
