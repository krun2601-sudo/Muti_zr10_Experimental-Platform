from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class _TargetEval:
    first_active_t: float
    discovery_t: float | None = None
    monitor_time_s: float = 0.0
    visible_time_s: float = 0.0
    total_loss_s: float = 0.0
    current_loss_s: float = 0.0
    max_loss_s: float = 0.0
    loss_episodes: int = 0
    previous_visible: bool = False
    previous_devices: frozenset[str] = field(default_factory=frozenset)
    overlap_source: str | None = None
    overlap_started_t: float | None = None


class ResearchEvaluator:
    """Ground-truth evaluator. Its private state is never returned to a policy.

    Monitoring loss is defined by valid geometric FOV visibility, not by whether a
    stochastic detector happened to fire on that frame. Detection/coasting remains
    available in tracks.csv, while the loss quantities here correspond exactly to
    the paper's continuous-monitoring requirement.
    """

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.targets: dict[str, _TargetEval] = {}
        self.entered_ids: set[str] = set()
        self.discovery_delays: list[float] = []
        self.handover_success = 0
        self.handover_without_overlap = 0
        self.handover_overlap_durations: list[float] = []
        self._handover_events: list[dict[str, Any]] = []
        self._last_t: float | None = None
        self.search_age_integral = 0.0
        self.elapsed_integral_s = 0.0

    def update(self, t: float, dt: float, target_status, search_snapshot) -> dict[str, float | int | None]:
        dt = max(0.0, float(dt))
        active_ids = set()
        for status in target_status:
            active_ids.add(status.truth_id)
            state = self.targets.get(status.truth_id)
            if state is None:
                state = _TargetEval(float(t))
                self.targets[status.truth_id] = state
                self.entered_ids.add(status.truth_id)
            if state.discovery_t is None and status.discovered and status.discovery_t is not None:
                state.discovery_t = float(status.discovery_t)
                self.discovery_delays.append(max(0.0, state.discovery_t - state.first_active_t))
            if state.discovery_t is None:
                state.previous_devices = frozenset(status.visible_devices)
                continue

            visible_devices = frozenset(status.visible_devices)
            visible = bool(visible_devices)
            state.monitor_time_s += dt
            if visible:
                state.visible_time_s += dt
                state.current_loss_s = 0.0
            else:
                state.total_loss_s += dt
                state.current_loss_s += dt
                state.max_loss_s = max(state.max_loss_s, state.current_loss_s)
                if state.previous_visible:
                    state.loss_episodes += 1

            # Handover accounting is geometric: a successful handover contains a
            # sampled source+destination overlap before the source disappears.
            prev = state.previous_devices
            if prev and visible_devices and prev.isdisjoint(visible_devices):
                self.handover_without_overlap += 1
                self._handover_events.append({
                    "event_type": "handover_without_overlap",
                    "t": float(t), "truth_id": status.truth_id,
                    "track_id": status.track_id or "",
                    "source_devices": tuple(sorted(prev)),
                    "destination_devices": tuple(sorted(visible_devices)),
                    "overlap_started_t": None, "overlap_duration_s": 0.0,
                    "successful": False,
                })
                state.overlap_source = None
                state.overlap_started_t = None
            elif len(prev) == 1 and len(visible_devices) >= 2 and next(iter(prev)) in visible_devices:
                source = next(iter(prev))
                state.overlap_source = source
                state.overlap_started_t = float(t)
                self._handover_events.append({
                    "event_type": "overlap_started",
                    "t": float(t), "truth_id": status.truth_id,
                    "track_id": status.track_id or "",
                    "source_devices": (source,),
                    "destination_devices": tuple(sorted(visible_devices - {source})),
                    "overlap_started_t": float(t), "overlap_duration_s": None,
                    "successful": None,
                })
            elif state.overlap_source is not None and visible_devices:
                if state.overlap_source not in visible_devices:
                    self.handover_success += 1
                    duration = (max(0.0, float(t) - state.overlap_started_t)
                                if state.overlap_started_t is not None else 0.0)
                    self.handover_overlap_durations.append(duration)
                    self._handover_events.append({
                        "event_type": "handover_success",
                        "t": float(t), "truth_id": status.truth_id,
                        "track_id": status.track_id or "",
                        "source_devices": (state.overlap_source,),
                        "destination_devices": tuple(sorted(visible_devices)),
                        "overlap_started_t": state.overlap_started_t,
                        "overlap_duration_s": duration,
                        "successful": True,
                    })
                    state.overlap_source = None
                    state.overlap_started_t = None
            state.previous_visible = visible
            state.previous_devices = visible_devices

        # Retired targets keep their accumulated metrics. Active status is not needed
        # after exit, so no hidden truth-derived values enter algorithm inputs.
        if search_snapshot is not None:
            self.search_age_integral += float(np.mean(search_snapshot.ages_s)) * dt
            self.elapsed_integral_s += dt
        self._last_t = float(t)
        return self.metrics(active_ids)

    def target_snapshot(self, truth_id: str) -> dict[str, float | int | None]:
        state = self.targets.get(truth_id)
        if state is None:
            return {
                "current_loss_gap_s": 0.0, "longest_loss_gap_s": 0.0,
                "total_loss_s": 0.0, "monitor_time_s": 0.0,
                "visible_time_s": 0.0, "loss_episodes": 0,
            }
        return {
            "current_loss_gap_s": float(state.current_loss_s),
            "longest_loss_gap_s": float(state.max_loss_s),
            "total_loss_s": float(state.total_loss_s),
            "monitor_time_s": float(state.monitor_time_s),
            "visible_time_s": float(state.visible_time_s),
            "loss_episodes": int(state.loss_episodes),
        }

    def drain_handover_events(self) -> tuple[dict[str, Any], ...]:
        events = tuple(self._handover_events)
        self._handover_events.clear()
        return events

    def metrics(self, active_ids: set[str] | None = None) -> dict[str, float | int | None]:
        discovered = [s for s in self.targets.values() if s.discovery_t is not None]
        monitor_time = sum(s.monitor_time_s for s in discovered)
        visible_time = sum(s.visible_time_s for s in discovered)
        total_loss = sum(s.total_loss_s for s in discovered)
        max_loss = max((s.max_loss_s for s in discovered), default=0.0)
        loss_episodes = sum(s.loss_episodes for s in discovered)
        handover_total = self.handover_success + self.handover_without_overlap
        return {
            "research_entered_target_count": len(self.entered_ids),
            "research_discovered_target_count": len(discovered),
            "research_discovery_rate": len(discovered) / max(len(self.entered_ids), 1),
            "research_detection_delay_mean_s": float(np.mean(self.discovery_delays)) if self.discovery_delays else None,
            "research_detection_delay_p95_s": float(np.percentile(self.discovery_delays, 95)) if self.discovery_delays else None,
            "research_monitor_visible_ratio": visible_time / max(monitor_time, 1e-12) if discovered else None,
            "research_total_loss_s": float(total_loss),
            "research_max_loss_gap_s": float(max_loss),
            "research_loss_episode_count": int(loss_episodes),
            "research_handover_success_count": int(self.handover_success),
            "research_handover_no_overlap_count": int(self.handover_without_overlap),
            "research_handover_success_rate": self.handover_success / handover_total if handover_total else None,
            "research_handover_overlap_mean_s": float(np.mean(self.handover_overlap_durations)) if self.handover_overlap_durations else None,
            "research_search_age_integral": float(self.search_age_integral),
            "research_active_target_count": len(active_ids or ()),
        }
