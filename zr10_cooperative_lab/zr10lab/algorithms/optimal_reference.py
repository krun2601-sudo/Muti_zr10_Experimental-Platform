"""OPT：小/中规模离线精确参考。

对每台设备枚举 viewpoint 子集并用 Held-Karp 动态规划求该子集的最短 open path，
随后用分支定界组合各设备路线以最小化 makespan。超过显式规模上限时直接报
unsupported_size；绝不静默退化为启发式。达到时间限制时返回 incumbent 并明确
标记 time_limit，同时报告一个保守的全局下界和 gap。
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time

from .coverage_base import CoveragePlanningError, CoverageRoutePolicy, RoutePlan, verify_routes
from .cooperative_greedy import build_cg_routes


@dataclass(frozen=True)
class _Option:
    coverage: int
    cost: float
    route: tuple[str, ...]


def _mask_from_cells(cells) -> int:
    out = 0
    for m in cells:
        out |= 1 << int(m)
    return out


def _held_karp_options(problem, did: str, max_viewpoints: int, deadline: float):
    vps = problem.viewpoints_by_device[did]
    n = len(vps)
    if n > max_viewpoints:
        raise CoveragePlanningError(
            f"OPT unsupported_size: {did} 有 {n} 个 viewpoint，超过 opt_max_viewpoints_per_device={max_viewpoints}")
    if n == 0:
        return [_Option(0, 0.0, ())]
    cov = [_mask_from_cells(v.covered_cell_ids) for v in vps]
    # dp[(subset,last)] = (cost, predecessor_last); predecessor subset 可由 bit 去除 last 得到。
    dp: dict[tuple[int, int], tuple[float, int | None]] = {}
    for j in range(n):
        dp[(1 << j, j)] = (float(problem.initial_transition_s[did][j]), None)
    for size in range(2, n + 1):
        if time.perf_counter() >= deadline:
            raise TimeoutError
        for mask in range(1, 1 << n):
            if mask.bit_count() != size:
                continue
            for last in range(n):
                if not (mask & (1 << last)):
                    continue
                prev_mask = mask ^ (1 << last)
                best = None
                for prev in range(n):
                    if not (prev_mask & (1 << prev)):
                        continue
                    old = dp.get((prev_mask, prev))
                    if old is None:
                        continue
                    candidate = old[0] + float(problem.transition_cost_s[did][prev, last])
                    if best is None or candidate < best[0]:
                        best = (candidate, prev)
                if best is not None:
                    dp[(mask, last)] = best

    by_coverage: dict[int, _Option] = {0: _Option(0, 0.0, ())}
    for mask in range(1, 1 << n):
        if time.perf_counter() >= deadline:
            raise TimeoutError
        ends = [(dp[(mask, j)][0], j) for j in range(n) if (mask, j) in dp]
        if not ends:
            continue
        cost, last = min(ends)
        route_idx = []
        walk_mask, walk_last = mask, last
        while walk_last is not None:
            route_idx.append(walk_last)
            _, predecessor = dp[(walk_mask, walk_last)]
            walk_mask ^= 1 << walk_last
            walk_last = predecessor
        route_idx.reverse()
        cmask = 0
        for j in route_idx:
            cmask |= cov[j]
        option = _Option(cmask, float(cost), tuple(vps[j].viewpoint_id for j in route_idx))
        old = by_coverage.get(cmask)
        if old is None or option.cost + 1e-12 < old.cost:
            by_coverage[cmask] = option

    # 去掉被“更便宜且覆盖超集”的选项。规模上限默认较小，因此 O(K^2) 可接受。
    options = sorted(by_coverage.values(), key=lambda o: (o.cost, -o.coverage.bit_count(), o.route))
    nondominated: list[_Option] = []
    for option in options:
        dominated = any(old.cost <= option.cost + 1e-12 and (old.coverage | option.coverage) == old.coverage
                        for old in nondominated)
        if not dominated:
            nondominated.append(option)
    return nondominated


def _lower_bound(problem, required_count: int) -> float:
    earliest = []
    for m in problem.cell_ids:
        best = math.inf
        for d in problem.device_ids:
            for vp in problem.candidates_covering(d, m):
                r = problem.viewpoint_index(d, vp.viewpoint_id)
                best = min(best, float(problem.initial_transition_s[d][r]))
        earliest.append(best)
    finite = sorted(x for x in earliest if math.isfinite(x))
    if len(finite) < required_count:
        return math.inf
    return float(finite[required_count - 1])


def solve_exact(problem, time_limit_s: float = 30.0, max_viewpoints: int = 10):
    started = time.perf_counter()
    deadline = started + max(.01, float(time_limit_s))
    required_count = max(1, math.ceil(problem.completion_threshold * len(problem.cells_m) - 1e-12))
    lower = _lower_bound(problem, required_count)

    try:
        heuristic, _ = build_cg_routes(problem)
        incumbent_routes = {d: tuple(heuristic[d]) for d in problem.device_ids}
        incumbent = problem.route_makespan(incumbent_routes)
    except Exception:
        incumbent_routes = None
        incumbent = math.inf

    try:
        options = {d: _held_karp_options(problem, d, max_viewpoints, deadline) for d in problem.device_ids}
    except TimeoutError:
        if incumbent_routes is None:
            raise CoveragePlanningError("OPT time_limit: 子路线动态规划未完成且没有可行 incumbent")
        return incumbent_routes, "time_limit", incumbent, lower, ((incumbent - lower) / incumbent if incumbent > 0 else 0.0), {
            "elapsed_s": time.perf_counter() - started, "stage": "per_device_dp"}

    devices = list(problem.device_ids)
    # 后缀最多可覆盖集合，用于不可行剪枝。
    suffix_union = [0] * (len(devices) + 1)
    for i in range(len(devices) - 1, -1, -1):
        union = 0
        for option in options[devices[i]]:
            union |= option.coverage
        suffix_union[i] = suffix_union[i + 1] | union

    best_routes = incumbent_routes
    best = incumbent
    timed_out = False
    chosen: dict[str, tuple[str, ...]] = {}

    def dfs(i: int, covered: int, current_max: float):
        nonlocal best, best_routes, timed_out
        if time.perf_counter() >= deadline:
            timed_out = True
            return
        if (covered | suffix_union[i]).bit_count() < required_count:
            return
        if current_max >= best - 1e-12:
            return
        if i == len(devices):
            if covered.bit_count() >= required_count:
                best = current_max
                best_routes = {d: tuple(chosen.get(d, ())) for d in devices}
            return
        d = devices[i]
        # 先搜低 cost / 高新增覆盖选项，尽快改善 incumbent。
        ordered = sorted(options[d], key=lambda o: (max(current_max, o.cost), -((o.coverage & ~covered).bit_count()), o.route))
        for option in ordered:
            next_max = max(current_max, option.cost)
            if next_max >= best - 1e-12:
                continue
            chosen[d] = option.route
            dfs(i + 1, covered | option.coverage, next_max)
            if timed_out:
                break
        chosen.pop(d, None)

    dfs(0, 0, 0.0)
    if best_routes is None or not math.isfinite(best):
        raise CoveragePlanningError("OPT infeasible: 枚举范围内不存在满足覆盖阈值的联合路线")
    verify_routes(problem, best_routes)
    status = "time_limit" if timed_out else "optimal"
    bound = lower if timed_out else best
    gap = max(0.0, (best - bound) / best) if best > 0 else 0.0
    return best_routes, status, best, bound, gap, {
        "elapsed_s": time.perf_counter() - started,
        "options_per_device": {d: len(options[d]) for d in devices},
        "required_cells": required_count,
    }


class OptimalReferencePolicy(CoverageRoutePolicy):
    algorithm_id = "opt"
    algorithm_version = "1.0"

    def plan_routes(self, context):
        limit = float(self.cfg.policy.get("opt_time_limit_s", 30.0))
        max_vp = int(self.cfg.policy.get("opt_max_viewpoints_per_device", 10))
        routes, status, objective, bound, gap, details = solve_exact(self.problem, limit, max_vp)
        return RoutePlan(routes, status=status, objective_s=objective,
                         best_bound_s=bound, gap=gap, details=details)
