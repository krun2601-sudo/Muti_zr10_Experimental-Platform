from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class TruthTarget:
    """Private virtual-target truth. Never pass this object to a policy."""

    truth_id: str
    t: float
    position: tuple[float, float, float]
    velocity: tuple[float, float, float]
    active: bool = True


@dataclass(frozen=True)
class ResearchTargetStatus:
    """Evaluation-only status containing the private truth/track association."""

    truth_id: str
    track_id: str | None
    active: bool
    discovered: bool
    visible_devices: tuple[str, ...]
    sensing_devices: tuple[str, ...]
    discovery_t: float | None
    current_loss_gap_s: float
    longest_loss_gap_s: float


@dataclass(frozen=True)
class DeviceReadiness:
    device_id: str
    sensing_valid: bool
    stable_since: float | None
    reason: str


@dataclass(frozen=True)
class SearchGridSnapshot:
    positions: np.ndarray
    ages_s: np.ndarray
    last_visit_s: np.ndarray
    observed_now: np.ndarray

    def policy_payload(self) -> dict[str, Any]:
        """Return only task information that is legitimate for a scheduler."""
        return {
            "positions_m": self.positions.copy(),
            "ages_s": self.ages_s.copy(),
            "observed_now": self.observed_now.astype(np.int8, copy=True),
        }


@dataclass(frozen=True)
class PerceptionSnapshot:
    tracks: tuple[Any, ...]
    detections: tuple[Any, ...]
    target_status: tuple[ResearchTargetStatus, ...]
    active_truth_count: int
    discovered_active_count: int


@dataclass
class SolverDiagnostics:
    method: str
    status: str = "not_run"
    solve_ms: float = 0.0
    mip_gap: float | None = None
    # Backward-compatible primary columns used by research_solver.csv:
    # level1 = target visibility loss [s]
    # level2 = normalized persistent-search utility
    # level3 = execution cost
    level1: float | None = None
    level2: float | None = None
    level3: float | None = None
    # Explicit names avoid hiding the additional handover-overlap lexicographic
    # level. These values are also copied to extras_json by as_dict().
    overlap_shortfall: float | None = None
    search_utility: float | None = None
    execution_cost: float | None = None
    candidate_count: int = 0
    timeout: bool = False
    extras: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        extras = dict(self.extras)
        extras.update({
            "overlap_shortfall": None if self.overlap_shortfall is None else float(self.overlap_shortfall),
            "search_utility": None if self.search_utility is None else float(self.search_utility),
            "execution_cost": None if self.execution_cost is None else float(self.execution_cost),
        })
        return {
            "method": self.method,
            "status": self.status,
            "solve_ms": float(self.solve_ms),
            "mip_gap": None if self.mip_gap is None else float(self.mip_gap),
            "level1": None if self.level1 is None else float(self.level1),
            "level2": None if self.level2 is None else float(self.level2),
            "level3": None if self.level3 is None else float(self.level3),
            "candidate_count": int(self.candidate_count),
            "timeout": bool(self.timeout),
            "extras": extras,
        }
