"""Time-aware Voronoi Partition (TVP)：按初始观测时间代价分区，并加入容量平衡。"""
from __future__ import annotations

from .coverage_base import CoveragePlanningError, CoverageRoutePolicy, RoutePlan, assigned_cells_to_routes, verify_routes


def build_tvp_routes(problem, balance_weight: float = 0.35, deadline=None):
    assigned = {d: set() for d in problem.device_ids}
    load = {d: 0.0 for d in problem.device_ids}
    for m in problem.cell_ids:
        choices = []
        for d in problem.device_ids:
            covering = problem.candidates_covering(d, m)
            if not covering:
                continue
            best = min(
                (float(problem.initial_transition_s[d][problem.viewpoint_index(d, vp.viewpoint_id)]), vp.viewpoint_id)
                for vp in covering
            )
            choices.append((best[0], d, best[1]))
        if not choices:
            raise CoveragePlanningError(f"cell {m} 不可达")
        # time-aware Voronoi：距离是云台初始指向到观测姿态的服务时间，不是欧氏空间距离。
        # capacity/makespan 平衡通过当前负载惩罚实现。
        service, d, _ = min(choices, key=lambda x: (x[0] + balance_weight * load[x[1]], load[x[1]], x[1]))
        assigned[d].add(m)
        load[d] += service
    routes = assigned_cells_to_routes(problem, assigned, use_two_opt=True, deadline=deadline)
    verify_routes(problem, routes)
    return routes, assigned, load


class TimeAwarePartitionPolicy(CoverageRoutePolicy):
    algorithm_id = "tvp"
    algorithm_version = "1.0"

    def plan_routes(self, context):
        weight = float(self.cfg.policy.get("tvp_balance_weight", 0.35))
        routes, assigned, load = build_tvp_routes(self.problem, weight)
        return RoutePlan(routes, status="heuristic", objective_s=self.problem.route_makespan(routes),
                         details={"balance_weight": weight,
                                  "assigned_cells": {d: len(v) for d, v in assigned.items()},
                                  "estimated_load": load})
