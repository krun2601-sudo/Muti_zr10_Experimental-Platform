"""Persistent-search / continuous-monitoring research extension.

The research package deliberately keeps virtual target truth separate from policy
inputs.  It reuses the platform geometry, device models, Action/Track contracts
and control-center plumbing, but does not inherit the original two-station
localization mission semantics.
"""

from .mission import SearchMonitorMission
from .target_field import VirtualTargetField

__all__ = ["SearchMonitorMission", "VirtualTargetField"]
