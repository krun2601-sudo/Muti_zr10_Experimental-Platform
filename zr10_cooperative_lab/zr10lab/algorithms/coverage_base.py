"""覆盖算法共享的规划工具与执行状态机。

各基线只负责生成 viewpoint 路线。本模块统一负责把路线转换为 Action，并依据
PolicyContext 中的真实 Telemetry 等待到位/稳定/驻留。严格覆盖完成条件由 runtime
中的 CoverageTracker 统一维护，策略本身不得修改 visited 状态。
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Iterable, Sequence

import numpy as np

from ..coverage import CoverageProblem
from ..models import Action, Decision, PolicyContext, Telemetry


class CoveragePlanningError(RuntimeError):
    pass


@dataclass(frozen=True)
class RoutePlan:
    routes: dict[str, tuple[str, ...]]
    status: str = "feasible"
    objective_s: float | None = None
    best_bound_s: float | None = None
    gap: float | None = None
    details: dict | None = None


def _cell_mask(n: int, ids: Iterable[int]) -> np.ndarray:
    mask = np.zeros(n, dtype=bool)
    mask[list(ids)] = True
    return mask


def route_mask(problem: CoverageProblem, route: Sequence[str]) -> np.ndarray:
    return _cell_mask(len(problem.cells_m), (
        m for vid in route for m in problem.viewpoint_lookup[vid].covered_cell_ids
    ))


def prune_redundant_route(problem: CoverageProblem, device_id: str, route: Sequence[str], required_mask: np.ndarray | None = None) -> tuple[str, ...]:
    """删除对所需覆盖没有独立贡献的 viewpoint；顺序不变。"""
    route = list(dict.fromkeys(route))
    required = np.ones(len(problem.cells_m), dtype=bool) if required_mask is None else np.asarray(required_mask, dtype=bool)
    changed = True
    while changed:
        changed = False
        for k in range(len(route) - 1, -1, -1):
            trial = route[:k] + route[k + 1:]
            if np.all(~required | route_mask(problem, trial)):
                route = trial
                changed = True
                break
    return tuple(route)


def greedy_set_cover(problem: CoverageProblem, device_id: str, required_cells: Iterable[int]) -> tuple[str, ...]:
    """单设备集合覆盖；只选择该设备能覆盖的 required cells。"""
    required = set(int(x) for x in required_cells)
    selected: list[str] = []
    while required:
        best = None
        best_gain = 0
        for vp in problem.viewpoints_by_device[device_id]:
            gain = len(required.intersection(vp.covered_cell_ids))
            if gain > best_gain or (gain == best_gain and gain > 0 and (best is None or vp.viewpoint_id < best.viewpoint_id)):
                best, best_gain = vp, gain
        if best is None or best_gain == 0:
            raise CoveragePlanningError(f"{device_id} 无法覆盖其分配的单元 {sorted(required)[:10]}")
        selected.append(best.viewpoint_id)
        required.difference_update(best.covered_cell_ids)
    return tuple(selected)


def nearest_neighbor_order(problem: CoverageProblem, device_id: str, viewpoint_ids: Sequence[str]) -> tuple[str, ...]:
    remaining = list(dict.fromkeys(viewpoint_ids))
    if not remaining:
        return ()
    order: list[str] = []
    current_index: int | None = None
    while remaining:
        candidates = []
        for vid in remaining:
            idx = problem.viewpoint_index(device_id, vid)
            cost = float(problem.initial_transition_s[device_id][idx]) if current_index is None else float(problem.transition_cost_s[device_id][current_index, idx])
            candidates.append((cost, vid, idx))
        _, vid, idx = min(candidates, key=lambda x: (x[0], x[1]))
        order.append(vid)
        remaining.remove(vid)
        current_index = idx
    return tuple(order)


def two_opt(problem: CoverageProblem, device_id: str, route: Sequence[str], deadline: float | None = None) -> tuple[str, ...]:
    best = tuple(route)
    best_cost = problem.route_cost(device_id, best)
    improved = True
    while improved:
        improved = False
        for i in range(max(0, len(best) - 2)):
            for j in range(i + 2, len(best)):
                if deadline is not None and time.perf_counter() >= deadline:
                    return best
                trial = best[:i] + tuple(reversed(best[i:j + 1])) + best[j + 1:]
                cost = problem.route_cost(device_id, trial)
                if cost + 1e-12 < best_cost:
                    best, best_cost, improved = trial, cost, True
                    break
            if improved:
                break
    return best


def assigned_cells_to_routes(problem: CoverageProblem, assignments: dict[str, set[int]], use_two_opt: bool = True, deadline: float | None = None) -> dict[str, tuple[str, ...]]:
    routes: dict[str, tuple[str, ...]] = {}
    for did in problem.device_ids:
        cells = assignments.get(did, set())
        if not cells:
            routes[did] = ()
            continue
        chosen = greedy_set_cover(problem, did, cells)
        route = nearest_neighbor_order(problem, did, chosen)
        if use_two_opt:
            route = two_opt(problem, did, route, deadline)
        routes[did] = route
    return routes


def verify_routes(problem: CoverageProblem, routes: dict[str, Sequence[str]]) -> None:
    if problem.required_views != 1:
        raise CoveragePlanningError(
            "当前 FS/EWP/CG/TVP/VGLS/OPT 基线只定义单站搜索覆盖(required_views=1)；"
            "多重覆盖必须使用专门的 multi-cover planner，不能静默按单覆盖求解。")
    unknown = [(d, vid) for d, route in routes.items() for vid in route
               if vid not in problem.viewpoint_lookup or problem.viewpoint_lookup[vid].device_id != d]
    if unknown:
        raise CoveragePlanningError(f"路线含未知或跨设备 viewpoint: {unknown[:5]}")
    mask = problem.route_coverage_mask(routes)
    fraction = float(np.mean(mask))
    if fraction + 1e-12 < problem.completion_threshold:
        missing = np.flatnonzero(~mask)
        raise CoveragePlanningError(f"规划路线只覆盖 {fraction:.3%}，缺失单元 {missing[:12].tolist()}")


class CoverageRoutePolicy:
    """所有离线路线型覆盖算法的统一执行状态机。"""

    algorithm_id = "coverage_base"
    algorithm_version = "1.1"

    def __init__(self, cfg):
        self.cfg = cfg
        self.problem = CoverageProblem(cfg)
        self.problem.assert_feasible()
        if self.problem.required_views != 1:
            raise CoveragePlanningError(
                "当前时间最优扫描基线只支持 required_views=1；"
                "该限制显式失败以避免把多站定位覆盖误当成单站搜索覆盖。")
        self.devices = self.problem.devices
        self.ttl_s = float(cfg.system.get("action_ttl_s", .5))
        self.angle_tolerance_deg = float(self.problem.options.get("arrival_tolerance_deg", .6))
        self.reset()

    def reset(self):
        self._plan: RoutePlan | None = None
        self._planning_ms = 0.0
        device_ids = self.problem.device_ids if hasattr(self, "problem") else ()
        self._route_index = {d: 0 for d in device_ids}
        self._stable_since: dict[str, float | None] = {d: None for d in device_ids}

    def plan_routes(self, context: PolicyContext) -> RoutePlan:
        raise NotImplementedError

    def _ensure_plan(self, context: PolicyContext) -> None:
        if self._plan is not None:
            return
        start = time.perf_counter()
        plan = self.plan_routes(context)
        self._planning_ms = (time.perf_counter() - start) * 1000.0
        routes = {d: tuple(plan.routes.get(d, ())) for d in self.problem.device_ids}
        verify_routes(self.problem, routes)
        self._plan = RoutePlan(routes, plan.status,
                               self.problem.route_makespan(routes) if plan.objective_s is None else plan.objective_s,
                               plan.best_bound_s, plan.gap, plan.details)

    def _available(self, context: PolicyContext, did: str) -> bool:
        state = context.devices.get(did)
        if state is None or not state.connected:
            return False
        return 0 <= context.t - state.t <= float(self.cfg.system.get("telemetry_stale_s", .5))

    def _at_viewpoint(self, state: Telemetry, vid: str) -> bool:
        vp = self.problem.viewpoint_lookup[vid]
        angle_error = math.hypot(state.yaw_deg - vp.yaw_deg, state.pitch_deg - vp.pitch_deg)
        rate = math.hypot(state.yaw_rate_dps, state.pitch_rate_dps)
        simulated = state.source == "simulation"
        zoom_ok = state.raw.get("zoom_known", simulated) and state.raw.get("zoom_stable", simulated) and abs(state.zoom - self.problem.fixed_zoom) <= float(self.problem.options.get("zoom_tolerance", .05))
        return angle_error <= self.angle_tolerance_deg and rate <= self.problem.settle_rate_dps and zoom_ok

    def _advance_progress(self, context: PolicyContext) -> None:
        if self._plan is None:
            return
        required_hold = self.problem.settle_s + self.problem.dwell_s
        for did in self.problem.device_ids:
            route = self._plan.routes[did]
            idx = self._route_index[did]
            if idx >= len(route) or not self._available(context, did):
                self._stable_since[did] = None
                continue
            state = context.devices[did]
            if self._at_viewpoint(state, route[idx]):
                since = self._stable_since[did]
                if since is None:
                    self._stable_since[did] = context.t
                elif context.t - since + 1e-12 >= required_hold:
                    self._route_index[did] += 1
                    self._stable_since[did] = None
            else:
                self._stable_since[did] = None

    def _hold_actions(self, context: PolicyContext, reason: str) -> dict[str, Action]:
        return {d: Action(d, issued_t=context.t, ttl_s=self.ttl_s, reason=f"{self.algorithm_id}:{reason}") for d in self.problem.device_ids}

    def decide(self, context: PolicyContext) -> Decision:
        if context.coverage.problem_hash and context.coverage.problem_hash != self.problem.problem_hash:
            raise CoveragePlanningError("PolicyContext.coverage.problem_hash 与策略 CoverageProblem 不一致；拒绝不公平比较")
        if context.coverage.complete:
            diagnostics = self._diagnostics(context, "coverage_complete")
            return Decision(self._hold_actions(context, "complete"), diagnostics, True, "coverage_complete")
        self._ensure_plan(context)
        self._advance_progress(context)
        actions: dict[str, Action] = {}
        for did in self.problem.device_ids:
            route = self._plan.routes[did] if self._plan else ()
            idx = self._route_index[did]
            if idx >= len(route):
                actions[did] = Action(did, issued_t=context.t, ttl_s=self.ttl_s, reason=f"{self.algorithm_id}:route_finished")
                continue
            if not self._available(context, did):
                actions[did] = Action(did, issued_t=context.t, ttl_s=self.ttl_s, reason=f"{self.algorithm_id}:unavailable")
                continue
            vp = self.problem.viewpoint_lookup[route[idx]]
            actions[did] = Action(
                device_id=did, yaw_deg=vp.yaw_deg, pitch_deg=vp.pitch_deg, zoom=None,
                issued_t=context.t, ttl_s=self.ttl_s, target_ids=(),
                reason=f"{self.algorithm_id}:{vp.viewpoint_id}")
        return Decision(actions, self._diagnostics(context, "running"))

    def _diagnostics(self, context: PolicyContext, state: str) -> dict:
        routes = self._plan.routes if self._plan else {d: () for d in self.problem.device_ids}
        assignments = {}
        for did in self.problem.device_ids:
            idx = self._route_index.get(did, 0)
            assignments[did] = routes[did][idx] if idx < len(routes[did]) else None
        solver = {
            "status": self._plan.status if self._plan else "not_planned",
            "objective_s": self._plan.objective_s if self._plan else None,
            "best_bound_s": self._plan.best_bound_s if self._plan else None,
            "gap": self._plan.gap if self._plan else None,
        }
        return {
            "algorithm_id": self.algorithm_id,
            "algorithm_version": self.algorithm_version,
            "problem_hash": self.problem.problem_hash,
            "planning_ms": self._planning_ms,
            "state": state,
            "current_device_viewpoint": assignments,
            "route_progress": {d: [self._route_index.get(d, 0), len(routes[d])] for d in self.problem.device_ids},
            "newly_covered_count": len(context.coverage.newly_covered_ids),
            "coverage_fraction": context.coverage.fraction,
            "solver": solver,
            "done": context.coverage.complete,
            "termination_reason": "coverage_complete" if context.coverage.complete else "",
        }
