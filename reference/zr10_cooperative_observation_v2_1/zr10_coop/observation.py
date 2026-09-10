from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from .types import GimbalSnapshot


class ObservationProvider(ABC):
    """Extension point for video detections, target tracks, fusion results, etc."""

    async def initialize(self) -> None:
        return None

    @abstractmethod
    async def collect(
        self,
        elapsed_s: float,
        device_states: Mapping[str, GimbalSnapshot],
    ) -> Mapping[str, Any]:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class NullObservationProvider(ObservationProvider):
    async def collect(
        self,
        elapsed_s: float,
        device_states: Mapping[str, GimbalSnapshot],
    ) -> Mapping[str, Any]:
        return {}
