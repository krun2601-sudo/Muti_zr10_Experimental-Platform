from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..recording import dumps
from .evaluation import ResearchEvaluator
from .perception import VirtualPerception
from .provenance import write_research_provenance
from .search_map import PersistentSearchMap, ReadinessTracker
from .target_field import VirtualTargetField


@dataclass(frozen=True)
class MissionStep:
    tracks: tuple
    detections: tuple
    policy_payload: dict[str, Any]
    metrics: dict[str, Any]
    truth_positions: dict[str, tuple[float, float, float]]


class SearchMonitorMission:
    """Authoritative virtual task layer for the paper experiments.

    The mission owns private target truth and evaluation. Algorithms only see
    anonymous target beliefs and the policy_payload. It can therefore be used
    identically in pure simulation and in the hardware-mirror environment.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.devices = {d.id: d for d in cfg.active_devices}
        self.target_field = VirtualTargetField(cfg)
        self.readiness = ReadinessTracker(cfg)
        self.search_map = PersistentSearchMap(cfg)
        self.perception = VirtualPerception(cfg)
        self.evaluator = ResearchEvaluator()
        self._last_t: float | None = None
        self._provenance_written = False
        self.last_truth = {}
        self.last_perception = None
        self.last_search = None
        self.last_readiness = {}
        self.last_metrics = {}

    @staticmethod
    def enabled(cfg) -> bool:
        return str(cfg.policy.get("mission", cfg.policy.get("research", {}).get("mission", ""))) == "search_monitor"

    def reset(self) -> None:
        self.readiness.reset()
        self.search_map.reset(0.0)
        self.perception.reset()
        self.evaluator.reset()
        self._last_t = None
        self._provenance_written = False
        self.last_truth = {}
        self.last_perception = None
        self.last_search = None
        self.last_readiness = {}
        self.last_metrics = {}

    def step(self, t: float, dt: float, states: dict) -> MissionStep:
        if self._last_t is not None and t < self._last_t - 1e-9:
            raise ValueError("research mission time moved backwards")
        truth = self.target_field.truth(float(t))
        readiness = self.readiness.update(float(t), states)
        search = self.search_map.update(float(t), states, readiness, self.devices)
        perception = self.perception.step(float(t), truth, states, readiness)
        metrics = self.search_map.metrics(float(t))
        metrics.update(self.evaluator.update(float(t), float(dt), perception.target_status, search))
        metrics.update({
            "research_sensing_ready_fraction": sum(x.sensing_valid for x in readiness.values()) / max(len(readiness), 1),
            "research_discovered_active_count": perception.discovered_active_count,
            "research_active_truth_count": perception.active_truth_count,
        })
        payload = {
            "mission": "search_monitor",
            "search": search.policy_payload(),
            "readiness": {key: {"sensing_valid": item.sensing_valid,
                                  "stable_since": item.stable_since,
                                  "reason": item.reason}
                          for key, item in readiness.items()},
            "execution": dict(self.cfg.policy.get("research", {}).get("execution", {})),
            "planning": dict(self.cfg.policy.get("research", {}).get("planning", {})),
        }
        self._last_t = float(t)
        self.last_truth = truth
        self.last_perception = perception
        self.last_search = search
        self.last_readiness = readiness
        self.last_metrics = metrics
        return MissionStep(
            tracks=perception.tracks,
            detections=perception.detections,
            policy_payload=payload,
            metrics=metrics,
            truth_positions={key: item.position for key, item in truth.items()},
        )

    def _ensure_provenance(self, recorder) -> None:
        if self._provenance_written:
            return
        raw = getattr(recorder, "recorder", recorder)
        path = getattr(raw, "path", None)
        if path is None:
            return
        write_research_provenance(path, cfg=self.cfg, extra={
            "environment": str(getattr(raw, "mode", "unknown")),
            "source": "research_mission",
        })
        self._provenance_written = True

    def record(self, recorder, t: float) -> None:
        """Write evaluation-only research tables. Safe to call once per cycle.

        ``research_targets`` uses geometric continuous-visibility loss gaps from
        ResearchEvaluator. Detector misses/coasting remain represented separately
        in ``tracks.csv`` and ``sensing_devices_json``.
        """
        if recorder is None or self.last_perception is None or self.last_search is None:
            return
        self._ensure_provenance(recorder)
        for status in self.last_perception.target_status:
            monitor = self.evaluator.target_snapshot(status.truth_id)
            recorder.write(
                "research_targets", t,
                truth_id=status.truth_id,
                track_id=status.track_id or "",
                active=status.active,
                discovered=status.discovered,
                visible_devices_json=dumps(status.visible_devices),
                sensing_devices_json=dumps(status.sensing_devices),
                discovery_t=status.discovery_t,
                current_loss_gap_s=monitor["current_loss_gap_s"],
                longest_loss_gap_s=monitor["longest_loss_gap_s"],
            )
        snap = self.last_search
        recorder.write(
            "research_search", t,
            cell_count=len(snap.positions),
            observed_count=int(snap.observed_now.sum()),
            mean_age_s=float(snap.ages_s.mean()),
            p95_age_s=float(__import__("numpy").percentile(snap.ages_s, 95)),
            max_age_s=float(snap.ages_s.max()),
            ages_json=dumps(snap.ages_s),
            observed_json=dumps(snap.observed_now.astype(int)),
        )
        for event in self.evaluator.drain_handover_events():
            recorder.event("research_handover", event, t)
