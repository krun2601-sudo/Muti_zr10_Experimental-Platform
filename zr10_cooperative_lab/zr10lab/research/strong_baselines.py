from __future__ import annotations

import math

from ..models import Decision
from .policies import MyopicGreedyPolicy
from .types import SolverDiagnostics


class ExecutionAwareMyopicGreedyPolicy(MyopicGreedyPolicy):
    """Strong one-step baseline using each candidate's earliest executable slot.

    This baseline intentionally receives the same physical candidate set as ECP-RH.
    It does *not* reject a motion merely because the device cannot finish it within
    the first 0.5 s prediction slot. Instead, each candidate is evaluated at its
    earliest sensing-valid slot. Selection is lexicographic on marginal current
    task value: newly covered targets, then freshness of newly covered search cells,
    then execution cost. It remains myopic because it does not optimize target
    continuity/search consequences across the full horizon or jointly reassign all
    devices.
    """

    def decide(self, context):
        self._check(context)
        ps = self.factory.generate(context)
        covered_targets: set[int] = set()
        covered_cells: set[int] = set()
        selected = []
        device_order = sorted(ps.by_device, key=lambda key: len(ps.by_device[key]))
        for key in device_order:
            best = None
            best_key = None
            best_h = 0
            for p in ps.by_device[key]:
                h = min(max(int(p.ready_slot), 0), ps.horizon_steps - 1)
                new_targets = {j for j in range(len(ps.target_ids)) if p.visibility[j, h]} - covered_targets
                new_cells = {g for g in range(len(ps.search_positions)) if p.search_coverage[g, h]} - covered_cells
                search_gain = sum(float(ps.search_ages_s[g]) + (h + 1) * ps.slot_s for g in new_cells)
                # Normalize freshness by grid size so target coverage is not
                # accidentally dominated merely because the ROI has many cells.
                normalized_search = search_gain / max(len(ps.search_positions), 1)
                key_tuple = (len(new_targets), normalized_search, -float(p.execution_cost))
                if best_key is None or key_tuple > best_key:
                    best, best_key, best_h = p, key_tuple, h
            if best is not None:
                selected.append(best)
                covered_targets |= {j for j in range(len(ps.target_ids)) if best.visibility[j, best_h]}
                covered_cells |= {g for g in range(len(ps.search_positions)) if best.search_coverage[g, best_h]}
        diag = SolverDiagnostics(
            "greedy", status="execution_aware_myopic", candidate_count=len(ps.flat),
            extras={"covered_targets": len(covered_targets), "covered_cells": len(covered_cells)},
        )
        return Decision(self._actions(context, selected, "greedy"), self._diag("greedy", diag))
