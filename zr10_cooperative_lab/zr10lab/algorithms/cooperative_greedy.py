"""Cooperative Greedy (CG)：单位时间新增覆盖收益的顺序协同贪心。"""
from __future__ import annotations

import math
import numpy as np

from .coverage_base import CoveragePlanningError, CoverageRoutePolicy, RoutePlan, verify_routes


def build_cg_routes(problem):
    uncovered = set(problem.cell_ids)
    routes = {d: [] for d in problem.device_ids}
    current = {d: None for d in problem.device_ids}
    rounds = 0
    while uncovered:
        rounds += 1
        progress = False
        # 每轮依次给设备选动作；前面的选择立即从边际收益中扣除，避免同轮重复抢同一区域。
        for d in problem.device_ids:
            candidates = []
            for r, vp in enumerate(problem.viewpoints_by_device[d]):
                new = len(uncovered.intersection(vp.covered_cell_ids))
                if new <= 0:
                    continue
                if current[d] is None:
                    cost = float(problem.initial_transition_s[d][r])
                else:
                    a = problem.viewpoint_index(d, current[d])
                    cost = float(problem.transition_cost_s[d][a, r])
                score = new / max(cost, 1e-9)
                candidates.append((score, new, -cost, vp.viewpoint_id))
            if not candidates:
                continue
            _, _, _, vid = max(candidates, key=lambda x: (x[0], x[1], x[2], -len(x[3])))
            routes[d].append(vid)
            current[d] = vid
            newly = uncovered.intersection(problem.viewpoint_lookup[vid].covered_cell_ids)
            if newly:
                uncovered.difference_update(newly)
                progress = True
            if not uncovered:
                break
        if not progress:
            raise CoveragePlanningError(f"CG 无法继续覆盖，剩余 {len(uncovered)} 个单元: {sorted(uncovered)[:12]}")
        if rounds > sum(len(v) for v in problem.viewpoints_by_device.values()) + 1:
            raise CoveragePlanningError("CG 超出有限候选数仍未完成，可能存在覆盖模型错误")
    result = {d: tuple(v) for d, v in routes.items()}
    verify_routes(problem, result)
    return result, rounds


class CooperativeGreedyPolicy(CoverageRoutePolicy):
    algorithm_id = "cg"
    algorithm_version = "1.0"

    def plan_routes(self, context):
        routes, rounds = build_cg_routes(self.problem)
        return RoutePlan(routes, status="greedy", objective_s=self.problem.route_makespan(routes),
                         details={"rounds": rounds})
