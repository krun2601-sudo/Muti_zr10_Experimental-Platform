"""Equal Workload Partition (EWP)：按预计扫描时间而非欧氏面积平衡任务。"""
from __future__ import annotations

import math

from .coverage_base import CoveragePlanningError, CoverageRoutePolicy, RoutePlan, assigned_cells_to_routes, verify_routes


def build_ewp_routes(problem, deadline=None):
    assigned = {d: set() for d in problem.device_ids}
    load = {d: 0.0 for d in problem.device_ids}
    # 难单元先分：可选设备少、最低服务成本高的单元优先，降低后期死锁风险。
    cells = []
    for m in problem.cell_ids:
        choices = []
        for d in problem.device_ids:
            for vp in problem.candidates_covering(d, m):
                idx = problem.viewpoint_index(d, vp.viewpoint_id)
                choices.append((float(problem.initial_transition_s[d][idx]), d, vp.viewpoint_id))
        if not choices:
            raise CoveragePlanningError(f"cell {m} 不可达")
        best_by_device = {}
        for cost, d, vid in choices:
            if d not in best_by_device or cost < best_by_device[d][0]:
                best_by_device[d] = (cost, vid)
        cells.append((len(best_by_device), -min(v[0] for v in best_by_device.values()), m, best_by_device))
    cells.sort(key=lambda x: (x[0], x[1], x[2]))
    for _, _, m, choices in cells:
        d, (service, _) = min(choices.items(), key=lambda item: (load[item[0]] + item[1][0], load[item[0]], item[0]))
        assigned[d].add(m)
        load[d] += service
    routes = assigned_cells_to_routes(problem, assigned, use_two_opt=False, deadline=deadline)
    verify_routes(problem, routes)
    return routes, assigned, load


class EqualWorkloadPolicy(CoverageRoutePolicy):
    algorithm_id = "ewp"
    algorithm_version = "1.0"

    def plan_routes(self, context):
        routes, assigned, estimated = build_ewp_routes(self.problem)
        return RoutePlan(routes, status="heuristic", objective_s=self.problem.route_makespan(routes),
                         details={"assigned_cells": {d: len(v) for d, v in assigned.items()},
                                  "estimated_workload": estimated})
