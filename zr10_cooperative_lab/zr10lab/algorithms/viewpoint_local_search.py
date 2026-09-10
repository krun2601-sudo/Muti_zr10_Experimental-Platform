"""Viewpoint-Graph Local Search (VGLS)。

借鉴近期 MCPP 的局部搜索思想，但在本项目统一 viewpoint/FoV 图上公平适配：
初始解取 EWP/TVP/CG 中最优者，随后执行 2-opt、冗余FoV替换、瓶颈任务转移
和跨设备任务交换。目标始终是最小化 max(T_i)，不改变 CoverageProblem 的几何
或时间模型。
"""
from __future__ import annotations

import time
import numpy as np

from .coverage_base import (CoveragePlanningError, CoverageRoutePolicy, RoutePlan,
                            greedy_set_cover, nearest_neighbor_order, two_opt, verify_routes)
from .cooperative_greedy import build_cg_routes
from .equal_workload import build_ewp_routes
from .time_aware_partition import build_tvp_routes


def _copy(routes):
    return {d: tuple(r) for d, r in routes.items()}


def _coverage_without(problem, routes, skips=()):
    skipped = set(skips)
    mask = np.zeros(len(problem.cells_m), dtype=bool)
    for d, route in routes.items():
        for k, vid in enumerate(route):
            if (d, k) in skipped:
                continue
            mask[list(problem.viewpoint_lookup[vid].covered_cell_ids)] = True
    return mask


def _rebuild_route(problem, did, base_route, required_cells, deadline):
    try:
        extra = greedy_set_cover(problem, did, required_cells) if required_cells else ()
    except CoveragePlanningError:
        return None
    merged = tuple(dict.fromkeys((*base_route, *extra)))
    ordered = nearest_neighbor_order(problem, did, merged)
    return two_opt(problem, did, ordered, deadline)


def build_vgls_routes(problem, time_budget_s=2.0, seed=7, tvp_balance_weight=.35):
    start = time.perf_counter()
    deadline = start + max(0.01, float(time_budget_s))
    rng = np.random.default_rng(seed)
    initials = []
    try:
        r, _ = build_cg_routes(problem); initials.append((problem.route_makespan(r), "cg", r))
    except CoveragePlanningError:
        pass
    try:
        r, _, _ = build_ewp_routes(problem, deadline); initials.append((problem.route_makespan(r), "ewp", r))
    except CoveragePlanningError:
        pass
    try:
        r, _, _ = build_tvp_routes(problem, tvp_balance_weight, deadline); initials.append((problem.route_makespan(r), "tvp", r))
    except CoveragePlanningError:
        pass
    if not initials:
        raise CoveragePlanningError("VGLS 的 EWP/TVP/CG 初始解均不可行")
    _, source, routes0 = min(initials, key=lambda x: (x[0], x[1]))
    best = _copy(routes0)
    best_obj = problem.route_makespan(best)
    move_counts = {"two_opt": 0, "replace": 0, "transfer": 0, "exchange": 0}

    # 先对每台设备执行确定性 2-opt。
    for d in problem.device_ids:
        if time.perf_counter() >= deadline:
            break
        trial = _copy(best)
        reordered = two_opt(problem, d, trial[d], deadline)
        if reordered != trial[d]:
            trial[d] = reordered
            obj = problem.route_makespan(trial)
            if obj + 1e-12 < best_obj:
                best, best_obj = trial, obj
                move_counts["two_opt"] += 1

    while time.perf_counter() < deadline:
        costs = {d: problem.route_cost(d, best[d]) for d in problem.device_ids}
        bottlenecks = sorted(problem.device_ids, key=lambda d: (-costs[d], d))
        improved = False
        for source_d in bottlenecks:
            if time.perf_counter() >= deadline:
                break
            indices = list(range(len(best[source_d])))
            rng.shuffle(indices)
            for k in indices:
                if time.perf_counter() >= deadline:
                    break
                vid = best[source_d][k]
                vp = problem.viewpoint_lookup[vid]
                covered_elsewhere = _coverage_without(problem, best, {(source_d, k)})
                exclusive = [m for m in vp.covered_cell_ids if not covered_elsewhere[m]]

                # 1) 同设备冗余 FoV 替换：保住 exclusive cells，减少路线时间。
                replacements = list(problem.viewpoints_by_device[source_d])
                rng.shuffle(replacements)
                for replacement in replacements:
                    if replacement.viewpoint_id == vid or not set(exclusive).issubset(replacement.covered_cell_ids):
                        continue
                    trial = _copy(best)
                    row = list(trial[source_d]); row[k] = replacement.viewpoint_id
                    trial[source_d] = two_opt(problem, source_d, tuple(dict.fromkeys(row)), deadline)
                    try:
                        verify_routes(problem, trial)
                    except CoveragePlanningError:
                        continue
                    obj = problem.route_makespan(trial)
                    if obj + 1e-9 < best_obj:
                        best, best_obj, improved = trial, obj, True
                        move_counts["replace"] += 1
                        break
                if improved:
                    break

                # 2) 瓶颈任务转移：删除 source viewpoint，把它独有的 cells 交给其他设备。
                targets = list(problem.device_ids)
                rng.shuffle(targets)
                for target_d in targets:
                    if target_d == source_d:
                        continue
                    if any(not problem.candidates_covering(target_d, m) for m in exclusive):
                        continue
                    trial = _copy(best)
                    src = list(trial[source_d]); src.pop(k)
                    trial[source_d] = two_opt(problem, source_d, tuple(src), deadline)
                    target_route = _rebuild_route(problem, target_d, trial[target_d], exclusive, deadline)
                    if target_route is None:
                        continue
                    trial[target_d] = target_route
                    try:
                        verify_routes(problem, trial)
                    except CoveragePlanningError:
                        continue
                    obj = problem.route_makespan(trial)
                    if obj + 1e-9 < best_obj:
                        best, best_obj, improved = trial, obj, True
                        move_counts["transfer"] += 1
                        break
                if improved:
                    break

                # 3) 跨设备任务交换：同时移除两台设备的一个 viewpoint，将彼此真正独有的
                #    覆盖需求交给对方重新选 FoV。它是“任务交换”而非直接交换 viewpoint，
                #    因为 viewpoint 是设备专属的本地 yaw/pitch 动作，不能跨设备复制。
                target_devices = [d for d in problem.device_ids if d != source_d and best[d]]
                rng.shuffle(target_devices)
                for target_d in target_devices:
                    target_indices = list(range(len(best[target_d])))
                    rng.shuffle(target_indices)
                    for j in target_indices:
                        if time.perf_counter() >= deadline:
                            break
                        target_vid = best[target_d][j]
                        target_vp = problem.viewpoint_lookup[target_vid]
                        remaining = _coverage_without(problem, best, {(source_d, k), (target_d, j)})
                        src_need = [m for m in vp.covered_cell_ids if not remaining[m]]
                        tgt_need = [m for m in target_vp.covered_cell_ids if not remaining[m]]
                        if any(not problem.candidates_covering(target_d, m) for m in src_need):
                            continue
                        if any(not problem.candidates_covering(source_d, m) for m in tgt_need):
                            continue
                        trial = _copy(best)
                        src_base = list(trial[source_d]); src_base.pop(k)
                        tgt_base = list(trial[target_d]); tgt_base.pop(j)
                        src_route = _rebuild_route(problem, source_d, tuple(src_base), tgt_need, deadline)
                        tgt_route = _rebuild_route(problem, target_d, tuple(tgt_base), src_need, deadline)
                        if src_route is None or tgt_route is None:
                            continue
                        trial[source_d] = src_route
                        trial[target_d] = tgt_route
                        try:
                            verify_routes(problem, trial)
                        except CoveragePlanningError:
                            continue
                        obj = problem.route_makespan(trial)
                        if obj + 1e-9 < best_obj:
                            best, best_obj, improved = trial, obj, True
                            move_counts["exchange"] += 1
                            break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                break
        if not improved:
            break
    verify_routes(problem, best)
    return best, {"initial_source": source, "move_counts": move_counts,
                  "moves": sum(move_counts.values()),
                  "elapsed_s": time.perf_counter() - start, "objective_s": best_obj}


class ViewpointLocalSearchPolicy(CoverageRoutePolicy):
    algorithm_id = "vgls"
    algorithm_version = "1.1"

    def plan_routes(self, context):
        budget = float(self.cfg.policy.get("planning_time_budget_s",
                                           self.problem.options.get("planning_time_budget_s", 2.0)))
        seed = int(self.cfg.policy.get("policy_seed", 7))
        balance = float(self.cfg.policy.get("tvp_balance_weight", .35))
        routes, details = build_vgls_routes(self.problem, budget, seed, balance)
        return RoutePlan(routes, status="time_budget_local_search",
                         objective_s=self.problem.route_makespan(routes), details=details)
