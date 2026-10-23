from __future__ import annotations

import numpy as np

from ..geometry import world_to_gimbal_angles
from ..models import Action, Decision
from .planning import angle_delta_deg
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


class PaperFixedScanReactivePolicy(FixedScanReactivePolicy):
    """Fair engineering baseline under the common effective-quality model.

    The baseline keeps simple partitioned cyclic scanning + reactive one-camera
    takeover, but it must obey the same PTZ mechanical limits and command a public
    quality-valid fixed search/track zoom. Unreachable cells are skipped rather
    than clipped by the action layer.
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        options = cfg.policy.get("research", {}).get("baselines", {}).get("fixed_scan", {})
        self.paper_search_zoom = float(options.get("search_zoom", 3.0))
        self.paper_track_zoom = float(options.get("track_zoom", 6.0))

    @staticmethod
    def _reachable(device, yaw: float, pitch: float, zoom: float) -> bool:
        return (device.yaw_limits_deg[0] - 1e-9 <= float(yaw) <= device.yaw_limits_deg[1] + 1e-9 and
                device.pitch_limits_deg[0] - 1e-9 <= float(pitch) <= device.pitch_limits_deg[1] + 1e-9 and
                device.zoom_limits[0] - 1e-9 <= float(zoom) <= device.zoom_limits[1] + 1e-9)

    def decide(self, context):
        self._check(context)
        search = context.research.get("search", {})
        positions = np.asarray(search.get("positions_m", []), dtype=float)
        tracks = sorted(context.tracks, key=lambda t: t.track_id)
        available = {key for key, state in context.devices.items() if state.connected}
        live_ids = {t.track_id for t in tracks}
        self.assignments = {tid: dev for tid, dev in self.assignments.items() if tid in live_ids and dev in available}
        used = set(self.assignments.values())
        track_zoom_cache = {}
        for track in tracks:
            if track.track_id in self.assignments:
                continue
            best = None
            for key in available - used:
                device = self.devices[key]
                state = context.devices[key]
                try:
                    yaw, pitch = world_to_gimbal_angles(track.position, device)
                except ValueError:
                    continue
                zoom = float(np.clip(self.paper_track_zoom, *device.zoom_limits))
                if not self._reachable(device, yaw, pitch, zoom):
                    continue
                cost = abs(angle_delta_deg(yaw, state.yaw_deg)) + abs(pitch - state.pitch_deg)
                if best is None or cost < best[0]:
                    best = (cost, key, zoom)
            if best is not None:
                self.assignments[track.track_id] = best[1]
                track_zoom_cache[(track.track_id, best[1])] = best[2]
                used.add(best[1])
        actions = {}
        reverse = {dev: tid for tid, dev in self.assignments.items()}
        track_map = {t.track_id: t for t in tracks}
        keys = sorted(available)
        for rank, key in enumerate(keys):
            state, device = context.devices[key], self.devices[key]
            tid = reverse.get(key)
            if tid is not None:
                track = track_map[tid]
                lead = np.asarray(track.position) + np.asarray(track.velocity) * min(0.5, self.factory.horizon_s / 2)
                try:
                    yaw, pitch = world_to_gimbal_angles(lead, device)
                    zoom = track_zoom_cache.get((tid, key), float(np.clip(self.paper_track_zoom, *device.zoom_limits)))
                    if self._reachable(device, yaw, pitch, zoom):
                        actions[key] = Action(key, yaw_deg=yaw, pitch_deg=pitch, zoom=zoom,
                                              target_ids=(tid,), reason="fixed_reactive_track",
                                              issued_t=context.t, ttl_s=self.ttl)
                        continue
                except ValueError:
                    pass
            if len(positions):
                partition = positions[rank::max(len(keys), 1)]
                if len(partition):
                    start = self.scan_index.get(key, 0) % len(partition)
                    chosen = None
                    for offset in range(len(partition)):
                        index = (start + offset) % len(partition)
                        point = partition[index]
                        try:
                            yaw, pitch = world_to_gimbal_angles(point, device)
                        except ValueError:
                            continue
                        zoom = float(np.clip(self.paper_search_zoom, *device.zoom_limits))
                        if self._reachable(device, yaw, pitch, zoom):
                            chosen = (index, yaw, pitch, zoom)
                            break
                    if chosen is not None:
                        index, yaw, pitch, zoom = chosen
                        if abs(angle_delta_deg(yaw, state.yaw_deg)) < 1.0 and abs(pitch - state.pitch_deg) < 1.0:
                            self.scan_index[key] = index + 1
                        else:
                            self.scan_index[key] = index
                        actions[key] = Action(key, yaw_deg=yaw, pitch_deg=pitch, zoom=zoom,
                                              reason="fixed_partition_scan", issued_t=context.t, ttl_s=self.ttl)
                        continue
            actions[key] = Action(key, yaw_deg=state.yaw_deg, pitch_deg=state.pitch_deg, zoom=state.zoom,
                                  reason="fixed_hold", issued_t=context.t, ttl_s=self.ttl)
        return Decision(actions, self._diag("fixed_scan", assignments=dict(self.assignments),
                                            fixed_search_zoom=self.paper_search_zoom,
                                            fixed_track_zoom=self.paper_track_zoom))


PAPER_POLICIES = {
    "ecprh": PaperECPRHPolicy,
    "weighted_rh": PaperWeightedRHPolicy,
    "greedy": PaperGreedyPolicy,
    "fixed_scan": PaperFixedScanReactivePolicy,
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
