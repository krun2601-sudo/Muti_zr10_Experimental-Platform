from __future__ import annotations

from dataclasses import dataclass
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix, csr_matrix, vstack

from .planning import Primitive, PrimitiveSet
from .types import SolverDiagnostics


@dataclass(frozen=True)
class _Layout:
    nx: int
    ns: int
    nq: int
    ny: int
    x0: int
    s0: int
    q0: int
    y0: int
    nvar: int


class PriorityHorizonMILP:
    """Always-feasible MILP for priority search/monitor scheduling.

    Variables
    ---------
    x_c : candidate primitive selection, binary.
    s_jh: target visibility shortfall in [0,1].
    q_r : overlap requirement satisfaction in [0,1]. A requirement for two
          simultaneous views is encoded as views >= 2*q_r. Thus a physically
          impossible overlap cannot make the whole problem infeasible; it becomes
          an explicit, measurable shortfall.
    y_gh: search-cell observation indicator in [0,1].

    ECP-RH solves four lexicographic levels:
      1) minimum target visibility loss,
      2) maximum handover-overlap satisfaction,
      3) maximum persistent-search freshness utility,
      4) minimum execution cost.

    ``time_limit_s`` is one total wall-clock MILP budget for a replanning call,
    not a fresh budget for each lexicographic level. If a higher-priority level is
    not certified optimal before the budget expires, lower levels are not optimized
    under an uncertified incumbent lock. Diagnostics explicitly distinguish a
    feasible incumbent from a certified lexicographic optimum.

    The weighted-RH baseline uses exactly the same variables and constraints but a
    finite weighted sum, so differences are attributable to priority structure
    rather than different physical action capabilities.
    """

    def __init__(self, primitive_set: PrimitiveSet, time_limit_s: float = 0.2,
                 mip_rel_gap: float = 1e-4):
        self.ps = primitive_set
        self.time_limit_s = max(float(time_limit_s), 1e-3)
        self.mip_rel_gap = max(float(mip_rel_gap), 0.0)
        self.C = len(primitive_set.flat)
        self.J = len(primitive_set.target_ids)
        self.H = primitive_set.horizon_steps
        self.G = len(primitive_set.search_positions)
        self.Q = len(primitive_set.overlap_requirements)
        ns, nq, ny = self.J * self.H, self.Q, self.G * self.H
        self.layout = _Layout(
            self.C, ns, nq, ny,
            0, self.C, self.C + ns, self.C + ns + nq,
            self.C + ns + nq + ny,
        )
        self._candidate_index = {p.index: i for i, p in enumerate(primitive_set.flat)}
        self._base_A, self._base_lb, self._base_ub = self._base_constraints()
        self.bounds = Bounds(np.zeros(self.layout.nvar), np.ones(self.layout.nvar))
        self.integrality = np.zeros(self.layout.nvar, dtype=int)
        self.integrality[:self.C] = 1

    def _base_constraints(self):
        rows: list[int] = []
        cols: list[int] = []
        data: list[float] = []
        lb: list[float] = []
        ub: list[float] = []
        row = 0

        for candidates in self.ps.by_device.values():
            if not candidates:
                continue
            for p in candidates:
                rows.append(row); cols.append(self._candidate_index[p.index]); data.append(1.0)
            lb.append(1.0); ub.append(1.0); row += 1

        for j in range(self.J):
            for h in range(self.H):
                for p in self.ps.flat:
                    if p.visibility[j, h]:
                        rows.append(row); cols.append(self._candidate_index[p.index]); data.append(1.0)
                s = self.layout.s0 + j * self.H + h
                rows.append(row); cols.append(s); data.append(1.0)
                lb.append(1.0); ub.append(np.inf); row += 1

        for g in range(self.G):
            for h in range(self.H):
                for p in self.ps.flat:
                    if p.search_coverage[g, h]:
                        rows.append(row); cols.append(self._candidate_index[p.index]); data.append(1.0)
                y = self.layout.y0 + g * self.H + h
                rows.append(row); cols.append(y); data.append(-1.0)
                lb.append(0.0); ub.append(np.inf); row += 1

        for r, (j, h, required) in enumerate(self.ps.overlap_requirements):
            for p in self.ps.flat:
                if p.visibility[j, h]:
                    rows.append(row); cols.append(self._candidate_index[p.index]); data.append(1.0)
            q = self.layout.q0 + r
            rows.append(row); cols.append(q); data.append(-float(required))
            lb.append(0.0); ub.append(np.inf); row += 1

        A = coo_matrix((data, (rows, cols)), shape=(row, self.layout.nvar)).tocsr()
        return A, np.asarray(lb, dtype=float), np.asarray(ub, dtype=float)

    def _search_weights(self) -> np.ndarray:
        if not self.G:
            return np.empty(0, dtype=float)
        weights = np.zeros(self.G * self.H, dtype=float)
        for g, age in enumerate(self.ps.search_ages_s):
            for h in range(self.H):
                weights[g * self.H + h] = max(0.0, float(age) + (h + 1) * self.ps.slot_s)
        scale = max(float(weights.max()), 1.0)
        return weights / scale

    def _constraints_with(self, extra_rows=None):
        if not extra_rows:
            return LinearConstraint(self._base_A, self._base_lb, self._base_ub)
        mats = [self._base_A]; lbs = [self._base_lb]; ubs = [self._base_ub]
        for vector, lower, upper in extra_rows:
            mats.append(csr_matrix(vector.reshape(1, -1)))
            lbs.append(np.asarray([lower], dtype=float))
            ubs.append(np.asarray([upper], dtype=float))
        return LinearConstraint(vstack(mats).tocsr(), np.concatenate(lbs), np.concatenate(ubs))

    def _solve(self, objective: np.ndarray, extra=None, *, time_limit_s: float | None = None):
        limit = self.time_limit_s if time_limit_s is None else max(float(time_limit_s), 1e-3)
        return milp(
            objective,
            integrality=self.integrality,
            bounds=self.bounds,
            constraints=self._constraints_with(extra),
            options={"time_limit": limit,
                     "mip_rel_gap": self.mip_rel_gap,
                     "presolve": True},
        )

    @staticmethod
    def _status(result) -> tuple[str, bool]:
        table = {0: "optimal", 1: "limit", 2: "infeasible", 3: "unbounded", 4: "error"}
        code = int(getattr(result, "status", 4))
        return table.get(code, "error"), code == 1

    @staticmethod
    def _optimal(result) -> bool:
        return int(getattr(result, "status", 4)) == 0 and getattr(result, "x", None) is not None

    def selected(self, x: np.ndarray | None) -> tuple[Primitive, ...]:
        if x is None:
            return ()
        return tuple(p for i, p in enumerate(self.ps.flat) if x[i] >= 0.5)

    def _visibility_loss(self, x) -> float | None:
        if x is None:
            return None
        return float(np.sum(x[self.layout.s0:self.layout.s0 + self.layout.ns]) * self.ps.slot_s)

    def _overlap_values(self, x) -> tuple[float | None, float | None]:
        if x is None:
            return None, None
        if not self.Q:
            return 0.0, 1.0
        q = x[self.layout.q0:self.layout.q0 + self.layout.nq]
        shortfall = float(np.sum(1.0 - q) * self.ps.slot_s)
        return shortfall, float(np.mean(q))

    def _search_utility(self, x, weights) -> float | None:
        if x is None:
            return None
        if not len(weights):
            return 0.0
        y = x[self.layout.y0:self.layout.y0 + self.layout.ny]
        return float(weights @ y)

    def _execution_cost(self, x) -> float | None:
        if x is None:
            return None
        return float(sum(p.execution_cost * x[i] for i, p in enumerate(self.ps.flat)))

    def _fill_diag(self, diag: SolverDiagnostics, x, weights) -> None:
        diag.level1 = self._visibility_loss(x)
        overlap_shortfall, overlap_fraction = self._overlap_values(x)
        diag.overlap_shortfall = overlap_shortfall
        diag.search_utility = self._search_utility(x, weights)
        diag.execution_cost = self._execution_cost(x)
        diag.level2 = diag.search_utility
        diag.level3 = diag.execution_cost
        diag.extras.update({
            "overlap_requirements": self.Q,
            "overlap_shortfall_s_equivalent": overlap_shortfall,
            "overlap_satisfaction_fraction": overlap_fraction,
            "horizon_steps": self.H,
            "slot_s": self.ps.slot_s,
            "total_solver_budget_s": self.time_limit_s,
        })

    def solve_lexicographic(self, method="ecprh") -> tuple[tuple[Primitive, ...], SolverDiagnostics]:
        start = time.perf_counter()
        deadline = start + self.time_limit_s
        diag = SolverDiagnostics(method=method, candidate_count=self.C)
        weights = self._search_weights()
        executed = []
        certification = {
            "visibility_level_certified": False,
            "overlap_level_certified": self.Q == 0,
            "search_level_certified": not len(weights),
            "execution_level_certified": False,
            "priority_certified": False,
        }

        def remaining() -> float:
            return max(0.0, deadline - time.perf_counter())

        def finish(result, *, budget_exhausted=False):
            diag.status = "/".join(self._status(r)[0] for r in executed)
            if budget_exhausted:
                diag.status = (diag.status + "/budget_exhausted").lstrip("/")
            diag.timeout = budget_exhausted or any(self._status(r)[1] for r in executed)
            diag.mip_gap = getattr(result, "mip_gap", None) if result is not None else None
            diag.solve_ms = (time.perf_counter() - start) * 1000.0
            if result is not None and result.x is not None:
                self._fill_diag(diag, result.x, weights)
            diag.extras.update(certification)
            diag.extras["levels_executed"] = len(executed)
            return self.selected(result.x if result is not None else None), diag

        c1 = np.zeros(self.layout.nvar)
        c1[self.layout.s0:self.layout.s0 + self.layout.ns] = self.ps.slot_s
        r1 = self._solve(c1, time_limit_s=remaining())
        executed.append(r1)
        if r1.x is None:
            return finish(r1)
        certification["visibility_level_certified"] = self._optimal(r1)
        if not certification["visibility_level_certified"]:
            # The incumbent is usable, but lower priorities must not be optimized
            # under a lock that has not been proven to be the level-1 optimum.
            return finish(r1)
        j1 = float(c1 @ r1.x)
        lock1 = (c1.copy(), -np.inf, j1 + 1e-7)
        current = r1

        lock_overlap = None
        if self.Q:
            if remaining() <= 1e-3:
                return finish(current, budget_exhausted=True)
            c_overlap = np.zeros(self.layout.nvar)
            c_overlap[self.layout.q0:self.layout.q0 + self.layout.nq] = -1.0
            r_overlap = self._solve(c_overlap, [lock1], time_limit_s=remaining())
            executed.append(r_overlap)
            if r_overlap.x is not None:
                current = r_overlap
            certification["overlap_level_certified"] = self._optimal(r_overlap)
            if not certification["overlap_level_certified"]:
                return finish(current)
            q_best = float(np.sum(r_overlap.x[self.layout.q0:self.layout.q0 + self.layout.nq]))
            q_vector = np.zeros(self.layout.nvar)
            q_vector[self.layout.q0:self.layout.q0 + self.layout.nq] = 1.0
            lock_overlap = (q_vector, q_best - 1e-7, np.inf)

        if len(weights):
            if remaining() <= 1e-3:
                return finish(current, budget_exhausted=True)
            c2 = np.zeros(self.layout.nvar)
            c2[self.layout.y0:self.layout.y0 + self.layout.ny] = -weights
            extra2 = [lock1] + ([lock_overlap] if lock_overlap is not None else [])
            r2 = self._solve(c2, extra2, time_limit_s=remaining())
            executed.append(r2)
            if r2.x is not None:
                current = r2
            certification["search_level_certified"] = self._optimal(r2)
            if not certification["search_level_certified"]:
                return finish(current)
            search_best = self._search_utility(r2.x, weights) or 0.0
            search_vector = np.zeros(self.layout.nvar)
            search_vector[self.layout.y0:self.layout.y0 + self.layout.ny] = weights
            lock_search = (search_vector, search_best - 1e-7, np.inf)
        else:
            extra2 = [lock1] + ([lock_overlap] if lock_overlap is not None else [])
            lock_search = None

        if remaining() <= 1e-3:
            return finish(current, budget_exhausted=True)
        c3 = np.zeros(self.layout.nvar)
        for i, p in enumerate(self.ps.flat):
            c3[i] = p.execution_cost
        extra3 = list(extra2) + ([lock_search] if lock_search is not None else [])
        r3 = self._solve(c3, extra3, time_limit_s=remaining())
        executed.append(r3)
        if r3.x is not None:
            current = r3
        certification["execution_level_certified"] = self._optimal(r3)
        certification["priority_certified"] = all([
            certification["visibility_level_certified"],
            certification["overlap_level_certified"],
            certification["search_level_certified"],
            certification["execution_level_certified"],
        ])
        return finish(current)

    def solve_weighted(self, loss_weight=10.0, overlap_weight=3.0,
                       search_weight=1.0, motion_weight=0.1,
                       method="weighted_rh") -> tuple[tuple[Primitive, ...], SolverDiagnostics]:
        start = time.perf_counter()
        c = np.zeros(self.layout.nvar)
        if self.layout.ns:
            c[self.layout.s0:self.layout.s0 + self.layout.ns] = float(loss_weight) / max(self.layout.ns, 1)
        if self.Q:
            c[self.layout.q0:self.layout.q0 + self.layout.nq] = -float(overlap_weight) / self.Q
        weights = self._search_weights()
        if len(weights):
            c[self.layout.y0:self.layout.y0 + self.layout.ny] = -float(search_weight) * weights / max(len(weights), 1)
        horizon = max(self.ps.horizon_steps * self.ps.slot_s, 1e-9)
        for i, p in enumerate(self.ps.flat):
            c[i] += float(motion_weight) * p.execution_cost / horizon
        result = self._solve(c, time_limit_s=self.time_limit_s)
        status, limit = self._status(result)
        diag = SolverDiagnostics(method=method, status=status, timeout=limit,
                                 solve_ms=(time.perf_counter() - start) * 1000.0,
                                 mip_gap=getattr(result, "mip_gap", None),
                                 candidate_count=self.C)
        self._fill_diag(diag, result.x, weights)
        diag.extras["weights"] = {
            "loss": float(loss_weight), "overlap": float(overlap_weight),
            "search": float(search_weight), "motion": float(motion_weight),
        }
        diag.extras["weighted_objective_certified"] = self._optimal(result)
        return self.selected(result.x), diag
