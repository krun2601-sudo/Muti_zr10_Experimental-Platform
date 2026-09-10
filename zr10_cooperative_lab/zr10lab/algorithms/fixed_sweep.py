"""Fixed Sweep (FS)：静态条带分区 + 固定蛇形扫描，不做在线优化。"""
from __future__ import annotations

import numpy as np

from .coverage_base import CoveragePlanningError, CoverageRoutePolicy, RoutePlan, greedy_set_cover, verify_routes


class FixedSweepPolicy(CoverageRoutePolicy):
    algorithm_id = "fs"
    algorithm_version = "1.0"

    def plan_routes(self, context):
        p = self.problem
        # 沿任务区域跨度最大的轴做固定条带；设备按该轴物理位置排序，规则确定且可复现。
        extents = [float(p.roi[a][1]) - float(p.roi[a][0]) for a in ("x", "y", "z")]
        axis = int(np.argmax(extents))
        devices = sorted(p.device_ids, key=lambda d: (p.devices[d].position_m[axis], d))
        coords = p.cells_m[:, axis]
        edges = np.linspace(float(np.min(coords)), float(np.max(coords)) + 1e-9, len(devices) + 1)
        assigned = {d: set() for d in devices}
        for m, value in enumerate(coords):
            stripe = min(len(devices) - 1, int(np.searchsorted(edges[1:], value, side="right")))
            preferred = devices[stripe]
            feasible = [d for d in devices if p.candidates_covering(d, m)]
            if not feasible:
                raise CoveragePlanningError(f"cell {m} 对所有设备不可达")
            # FS 保持固定分区；仅当该条带设备物理不可达时，使用确定性的最近可行站兜底。
            if preferred not in feasible:
                preferred = min(feasible, key=lambda d: (
                    min(p.initial_transition_s[d][p.viewpoint_index(d, vp.viewpoint_id)] for vp in p.candidates_covering(d, m)), d))
            assigned[preferred].add(m)

        routes = {}
        for d in devices:
            chosen = list(greedy_set_cover(p, d, assigned[d])) if assigned[d] else []
            # 固定蛇形：按 z 层、次轴、主轴排序；不依据转移成本优化顺序。
            def key(vid):
                vp = p.viewpoint_lookup[vid]
                x, y, z = vp.aim_point_m
                layer = round(z, 9)
                row = round((y if axis != 1 else x), 9)
                primary = x if axis == 0 else (y if axis == 1 else x)
                parity = int(abs(hash((layer, row))) % 2)
                return (layer, row, primary if parity == 0 else -primary, vid)
            routes[d] = tuple(sorted(chosen, key=key))
        verify_routes(p, routes)
        return RoutePlan(routes, status="fixed_rule", objective_s=p.route_makespan(routes),
                         details={"partition_axis": ("x", "y", "z")[axis]})
