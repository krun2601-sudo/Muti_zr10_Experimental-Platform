"""本文创新算法预留接口。

用户尚未定义 Proposed 的算法思想，因此本文件故意不提供伪造策略或性能结论。
注册入口存在，误运行时明确失败，而不是偷偷调用某个基线。
"""
from __future__ import annotations

from .coverage_base import CoverageRoutePolicy, CoveragePlanningError


class ProposedCoveragePolicy(CoverageRoutePolicy):
    algorithm_id = "proposed"
    algorithm_version = "0.0-placeholder"

    def plan_routes(self, context):
        raise CoveragePlanningError(
            "ProposedCoveragePolicy 仅为可替换接口：尚未定义本文创新算法，"
            "因此不会退化为 FS/EWP/CG/TVP/VGLS/OPT 中的任何一种。")
