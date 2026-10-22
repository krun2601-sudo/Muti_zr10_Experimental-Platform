from __future__ import annotations

from itertools import combinations
import math
import time

import numpy as np

from ..geometry import world_to_gimbal_angles
from ..models import Action, Decision, PolicyContext
from .planning import HorizonMILP, Primitive, PrimitiveFactory, angle_delta_deg
from .types import SolverDiagnostics


class _ResearchPolicy:
    def __init__(self, cfg):
        self.cfg = cfg
        self.devices = {d.id: d for d in cfg.active_devices}
        self.factory = PrimitiveFactory(cfg)
        self.ttl = self.factory.ttl_s
        self.reset()

    def reset(self):
        self.last_selected: dict[str, Primitive] = {}

    def _check(self, context: PolicyContext):
        if context.research.get("mission") != "search_monitor":
            raise ValueError("research policy requires mission: search_monitor")

    def _holds(self, context, reason="research_hold"):
        return {key: Action(key, yaw_deg=state.yaw_deg, pitch_deg=state.pitch_deg, zoom=state.zoom,
                            issued_t=context.t, ttl_s=self.ttl, reason=reason)
                for key, state in context.devices.items() if state.connected}

    def _actions(self, context, selected, reason_prefix="research"):
        chosen = {p.device_id: p for p in selected}
        actions = {}
        for key, state in context.devices.items():
            if not state.connected:
                continue
            p = chosen.get(key)
            if p is None:
                actions[key] = Action(key, yaw_deg=state.yaw_deg, pitch_deg=state.pitch_deg,
                                      zoom=state.zoom, issued_t=context.t, ttl_s=self.ttl,
                                      reason=f"{reason_prefix}_fallback_hold")
            else:
                actions[key] = Action(key, yaw_deg=p.yaw_deg, pitch_deg=p.pitch_deg, zoom=p.zoom,
                                      target_ids=p.target_ids, issued_t=context.t, ttl_s=self.ttl,
                                      reason=f"{reason_prefix}_{p.kind}")
                self.last_selected[key] = p
        return actions

    @staticmethod
    def _diag(algorithm, solver: SolverDiagnostics | None = None, **extra):
        result = {"algorithm": algorithm, **extra}
        if solver is not None:
            result["solver"] = solver.as_dict()
        return result


class ECPRHPolicy(_ResearchPolicy):
    """Proposed execution-constrained priority receding-horizon scheduler."""

    def __init__(self, cfg):
        super().__init__(cfg)
        planning = cfg.policy.get("research", {}).get("planning", {})
        self.time_limit_s = float(planning.get("solver_time_limit_s", 0.2))
        self.mip_gap = float(planning.get("solver_mip_rel_gap", 1e-4))

    def decide(self, context: PolicyContext) -> Decision:
        self._check(context)
        ps = self.factory.generate(context)
        if not ps.flat:
            return Decision(self._holds(context, "ecprh_no_candidate"), self._diag("ecprh", candidate_count=0))
        solver = HorizonMILP(ps, self.time_limit_s, self.mip_gap)
        selected, diag = solver.solve_lexicographic("ecprh")
        actions = self._actions(context, selected, "ecprh") if selected else self._holds(context, "ecprh_solver_fallback")
        return Decision(actions, self._diag("ecprh", diag,
            target_count=len(ps.target_ids), overlap_constraints=len(ps.overlap_requirements)))


class WeightedRHPolicy(_ResearchPolicy):
    """Strong same-model weighted receding-horizon MPC baseline."""

    def __init__(self, cfg):
        super().__init__(cfg)
        planning = cfg.policy.get("research", {}).get("planning", {})
        weights = cfg.policy.get("research", {}).get("baselines", {}).get("weighted_rh", {})
        self.loss_weight = float(weights.get("loss_weight", 10.0))
        self.search_weight = float(weights.get("search_weight", 1.0))
        self.motion_weight = float(weights.get("motion_weight", 0.1))
        self.time_limit_s = float(planning.get("solver_time_limit_s", 0.2))
        self.mip_gap = float(planning.get("solver_mip_rel_gap", 1e-4))

    def decide(self, context: PolicyContext) -> Decision:
        self._check(context)
        ps = self.factory.generate(context)
        if not ps.flat:
            return Decision(self._holds(context, "weighted_no_candidate"), self._diag("weighted_rh"))
        solver = HorizonMILP(ps, self.time_limit_s, self.mip_gap)
        selected, diag = solver.solve_weighted(self.loss_weight, self.search_weight, self.motion_weight)
        actions = self._actions(context, selected, "weighted_rh") if selected else self._holds(context, "weighted_solver_fallback")
        return Decision(actions, self._diag("weighted_rh", diag, weights={
            "loss": self.loss_weight, "search": self.search_weight, "motion": self.motion_weight}))


class MyopicGreedyPolicy(_ResearchPolicy):
    """One-step greedy baseline using the common executable primitive set."""

    def __init__(self, cfg):
        super().__init__(cfg)
        opt = cfg.policy.get("research", {}).get("baselines", {}).get("greedy", {})
        self.loss_value = float(opt.get("target_value", 100.0))
        self.search_value = float(opt.get("search_value", 1.0))
        self.motion_cost = float(opt.get("motion_cost", 0.1))

    def decide(self, context: PolicyContext) -> Decision:
        self._check(context)
        ps = self.factory.generate(context)
        covered_targets: set[int] = set()
        covered_cells: set[int] = set()
        selected = []
        # Greedy intentionally values only the earliest planning slot.  Movement
        # that pays off later therefore needs the proposed look-ahead method.
        h = 0
        device_order = sorted(ps.by_device, key=lambda key: len(ps.by_device[key]))
        for key in device_order:
            best, best_score = None, -math.inf
            for p in ps.by_device[key]:
                new_targets = {j for j in range(len(ps.target_ids)) if p.visibility[j, h]} - covered_targets
                new_cells = {g for g in range(len(ps.search_positions)) if p.search_coverage[g, h]} - covered_cells
                search_gain = sum(float(ps.search_ages_s[g]) + ps.slot_s for g in new_cells)
                score = self.loss_value * len(new_targets) + self.search_value * search_gain - self.motion_cost * p.execution_cost
                if score > best_score + 1e-12:
                    best, best_score = p, score
            if best is not None:
                selected.append(best)
                covered_targets |= {j for j in range(len(ps.target_ids)) if best.visibility[j, h]}
                covered_cells |= {g for g in range(len(ps.search_positions)) if best.search_coverage[g, h]}
        diag = SolverDiagnostics("greedy", status="heuristic", candidate_count=len(ps.flat),
                                 extras={"covered_targets_h0": len(covered_targets), "covered_cells_h0": len(covered_cells)})
        return Decision(self._actions(context, selected, "greedy"), self._diag("greedy", diag))


class FixedScanReactivePolicy(_ResearchPolicy):
    """Engineering baseline: fixed search partitions + reactive target takeover."""

    def reset(self):
        super().reset()
        self.scan_index: dict[str, int] = {}
        self.assignments: dict[str, str] = {}

    def decide(self, context: PolicyContext) -> Decision:
        self._check(context)
        search = context.research.get("search", {})
        positions = np.asarray(search.get("positions_m", []), dtype=float)
        tracks = sorted(context.tracks, key=lambda t: t.track_id)
        available = {key for key, state in context.devices.items() if state.connected}
        # Preserve target assignments while target exists and device remains usable.
        live_ids = {t.track_id for t in tracks}
        self.assignments = {tid: dev for tid, dev in self.assignments.items() if tid in live_ids and dev in available}
        used = set(self.assignments.values())
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
                cost = abs(angle_delta_deg(yaw, state.yaw_deg)) + abs(pitch - state.pitch_deg)
                if best is None or cost < best[0]:
                    best = (cost, key)
            if best is not None:
                self.assignments[track.track_id] = best[1]
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
                    zoom = float(np.clip(5.0, *device.zoom_limits))
                    actions[key] = Action(key, yaw_deg=yaw, pitch_deg=pitch, zoom=zoom,
                                          target_ids=(tid,), reason="fixed_reactive_track",
                                          issued_t=context.t, ttl_s=self.ttl)
                    continue
                except ValueError:
                    pass
            if len(positions):
                partition = positions[rank::max(len(keys), 1)]
                if len(partition):
                    index = self.scan_index.get(key, 0) % len(partition)
                    point = partition[index]
                    try:
                        yaw, pitch = world_to_gimbal_angles(point, device)
                        if abs(angle_delta_deg(yaw, state.yaw_deg)) < 1.0 and abs(pitch - state.pitch_deg) < 1.0:
                            self.scan_index[key] = index + 1
                        zoom = float(device.zoom_limits[0])
                        actions[key] = Action(key, yaw_deg=yaw, pitch_deg=pitch, zoom=zoom,
                                              reason="fixed_partition_scan", issued_t=context.t, ttl_s=self.ttl)
                        continue
                    except ValueError:
                        pass
            actions[key] = Action(key, yaw_deg=state.yaw_deg, pitch_deg=state.pitch_deg, zoom=state.zoom,
                                  reason="fixed_hold", issued_t=context.t, ttl_s=self.ttl)
        return Decision(actions, self._diag("fixed_scan", assignments=dict(self.assignments)))


class ClassicalPTZPolicy(_ResearchPolicy):
    """Adapted classical constrained PTZ utility baseline.

    It is deliberately one-step/value-risk based: tracking quality is favored,
    while remaining PTZ freedom is used opportunistically for search.  It is not
    presented as the original authors' source-code reproduction.
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        opt = cfg.policy.get("research", {}).get("baselines", {}).get("classical_ptz", {})
        self.track_weight = float(opt.get("track_weight", 4.0))
        self.search_weight = float(opt.get("search_weight", 1.0))
        self.risk_weight = float(opt.get("risk_weight", 2.0))
        self.motion_weight = float(opt.get("motion_weight", 0.15))

    def decide(self, context: PolicyContext) -> Decision:
        self._check(context)
        ps = self.factory.generate(context)
        selected, target_counts, cell_covered = [], np.zeros(len(ps.target_ids)), set()
        for key in sorted(ps.by_device):
            best, score_best = None, -math.inf
            for p in ps.by_device[key]:
                # First executable sensing slot represents classical current-value planning.
                h = min(max(p.ready_slot, 0), ps.horizon_steps - 1)
                target_gain = sum(1.0 / (1.0 + target_counts[j]) for j in range(len(ps.target_ids)) if p.visibility[j, h])
                cells = {g for g in range(len(ps.search_positions)) if p.search_coverage[g, h]}
                search_gain = sum((float(ps.search_ages_s[g]) + ps.slot_s) for g in cells - cell_covered)
                uncovered_risk = sum(1 for j in range(len(ps.target_ids)) if target_counts[j] == 0 and not p.visibility[j, h])
                score = (self.track_weight * target_gain + self.search_weight * search_gain / max(len(ps.search_positions), 1)
                         - self.risk_weight * uncovered_risk - self.motion_weight * p.execution_cost)
                if score > score_best:
                    best, score_best = p, score
            if best is not None:
                selected.append(best)
                h = min(max(best.ready_slot, 0), ps.horizon_steps - 1)
                target_counts += best.visibility[:, h]
                cell_covered |= {g for g in range(len(ps.search_positions)) if best.search_coverage[g, h]}
        diag = SolverDiagnostics("classical_ptz", status="adapted_heuristic", candidate_count=len(ps.flat))
        return Decision(self._actions(context, selected, "classical_ptz"), self._diag("classical_ptz", diag))


class InformationPlannerPolicy(_ResearchPolicy):
    """Discovery/tracking information-value greedy planner inspired by RFS/TSP work."""

    def __init__(self, cfg):
        super().__init__(cfg)
        opt = cfg.policy.get("research", {}).get("baselines", {}).get("info_planner", {})
        self.track_information_weight = float(opt.get("track_information_weight", 1.0))
        self.discovery_weight = float(opt.get("discovery_weight", 1.0))
        self.motion_weight = float(opt.get("motion_weight", 0.05))

    def decide(self, context: PolicyContext) -> Decision:
        self._check(context)
        ps = self.factory.generate(context)
        selected = []
        covered_target_slots: set[tuple[int, int]] = set()
        covered_search_slots: set[tuple[int, int]] = set()
        track_map = {t.track_id: t for t in context.tracks}
        info_weight = []
        for tid in ps.target_ids:
            covariance = np.asarray(track_map[tid].covariance, dtype=float)
            sign, logdet = np.linalg.slogdet(covariance + np.eye(3) * 1e-9)
            info_weight.append(max(0.0, float(logdet)) if sign > 0 else 0.0)
        for key in sorted(ps.by_device):
            best, score_best = None, -math.inf
            for p in ps.by_device[key]:
                track_gain = 0.0
                for j in range(len(ps.target_ids)):
                    for h in range(ps.horizon_steps):
                        if p.visibility[j, h] and (j, h) not in covered_target_slots:
                            track_gain += 1.0 + info_weight[j]
                search_gain = 0.0
                for g in range(len(ps.search_positions)):
                    for h in range(ps.horizon_steps):
                        if p.search_coverage[g, h] and (g, h) not in covered_search_slots:
                            search_gain += float(ps.search_ages_s[g]) + (h + 1) * ps.slot_s
                score = self.track_information_weight * track_gain + self.discovery_weight * search_gain - self.motion_weight * p.execution_cost
                if score > score_best:
                    best, score_best = p, score
            if best is not None:
                selected.append(best)
                covered_target_slots |= {(j, h) for j in range(len(ps.target_ids)) for h in range(ps.horizon_steps) if best.visibility[j, h]}
                covered_search_slots |= {(g, h) for g in range(len(ps.search_positions)) for h in range(ps.horizon_steps) if best.search_coverage[g, h]}
        diag = SolverDiagnostics("info_planner", status="greedy_information", candidate_count=len(ps.flat),
                                 extras={"target_slot_coverage": len(covered_target_slots), "search_slot_coverage": len(covered_search_slots)})
        return Decision(self._actions(context, selected, "info_planner"), self._diag("info_planner", diag))


class SSMBeliefPolicy(_ResearchPolicy):
    """Finite-candidate simultaneous-search/monitoring belief-lookahead baseline.

    This is a documented adaptation of the SSM idea to fixed PTZ execution.  It
    uses a discounted finite-horizon joint utility rather than claiming an exact
    reproduction of a particular POMDP solver.
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        opt = cfg.policy.get("research", {}).get("baselines", {}).get("ssm", {})
        self.gamma = float(opt.get("gamma", 0.92))
        self.monitor_weight = float(opt.get("monitor_weight", 4.0))
        self.search_weight = float(opt.get("search_weight", 1.0))
        self.motion_weight = float(opt.get("motion_weight", 0.08))

    def _joint_value(self, chosen: list[Primitive], ps) -> float:
        value = 0.0
        for h in range(ps.horizon_steps):
            discount = self.gamma ** h
            visible = np.zeros(len(ps.target_ids), dtype=bool)
            searched = np.zeros(len(ps.search_positions), dtype=bool)
            for p in chosen:
                if len(visible): visible |= p.visibility[:, h]
                if len(searched): searched |= p.search_coverage[:, h]
            monitor = float(visible.sum())
            search = float(np.sum((ps.search_ages_s + (h + 1) * ps.slot_s) * searched))
            value += discount * (self.monitor_weight * monitor + self.search_weight * search / max(len(searched), 1))
        value -= self.motion_weight * sum(p.execution_cost for p in chosen)
        return value

    def decide(self, context: PolicyContext) -> Decision:
        self._check(context)
        ps = self.factory.generate(context)
        selected: list[Primitive] = []
        for key in sorted(ps.by_device):
            best, best_value = None, -math.inf
            for p in ps.by_device[key]:
                value = self._joint_value([*selected, p], ps)
                if value > best_value:
                    best, best_value = p, value
            if best is not None:
                selected.append(best)
        diag = SolverDiagnostics("ssm_belief", status="finite_horizon_belief_heuristic",
                                 candidate_count=len(ps.flat), extras={"joint_value": self._joint_value(selected, ps)})
        return Decision(self._actions(context, selected, "ssm_belief"), self._diag("ssm_belief", diag))


POLICIES = {
    "ecprh": ECPRHPolicy,
    "weighted_rh": WeightedRHPolicy,
    "greedy": MyopicGreedyPolicy,
    "fixed_scan": FixedScanReactivePolicy,
    "classical_ptz": ClassicalPTZPolicy,
    "info_planner": InformationPlannerPolicy,
    "ssm_belief": SSMBeliefPolicy,
}


def build_research_policy(name: str, cfg):
    try:
        return POLICIES[name](cfg)
    except KeyError as exc:
        raise ValueError(f"unknown research policy {name!r}; choose from {sorted(POLICIES)}") from exc
