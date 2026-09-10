"""严格协同覆盖基线。

所有算法只依赖 config/models/coverage/geometry，禁止导入 hardware、simulation、SDK 或 truth。
"""

from .fixed_sweep import FixedSweepPolicy
from .equal_workload import EqualWorkloadPolicy
from .cooperative_greedy import CooperativeGreedyPolicy
from .time_aware_partition import TimeAwarePartitionPolicy
from .viewpoint_local_search import ViewpointLocalSearchPolicy
from .optimal_reference import OptimalReferencePolicy
from .proposed import ProposedCoveragePolicy

__all__ = [
    "FixedSweepPolicy", "EqualWorkloadPolicy", "CooperativeGreedyPolicy",
    "TimeAwarePartitionPolicy", "ViewpointLocalSearchPolicy",
    "OptimalReferencePolicy", "ProposedCoveragePolicy",
]
