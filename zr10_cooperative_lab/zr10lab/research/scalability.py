from __future__ import annotations

import argparse
import copy
import csv
import math
from pathlib import Path
import time

import numpy as np

from ..config import load_config
from ..models import PolicyContext, Track
from ..simulation import SimulationWorld
from .optimization import PriorityHorizonMILP
from .priority_policies import _ConfigurableExecutionFactory


def _search_grid(cfg):
    search = cfg.policy.get("research", {}).get("search", {})
    roi = search.get("roi", cfg.policy.get("research", {}).get("scenario", {}).get("roi"))
    shape = search.get("grid", [7, 9, 3])
    axes = [np.linspace(float(roi[k][0]), float(roi[k][1]), int(shape[i]))
            for i, k in enumerate(("x", "y", "z"))]
    positions = np.asarray(np.meshgrid(*axes, indexing="ij"), dtype=float)
    return positions.reshape(3, -1).T


def _tracks(cfg, count):
    roi = cfg.policy.get("research", {}).get("scenario", {}).get("roi",
          cfg.policy.get("research", {}).get("search", {}).get("roi"))
    x0, x1 = map(float, roi["x"]); y0, y1 = map(float, roi["y"]); z0, z1 = map(float, roi["z"])
    devices = [d.id for d in cfg.active_devices]
    rows = []
    for j in range(int(count)):
        alpha = (j + 1) / (count + 1) if count else 0.5
        # Deterministic spread covers center and edges without any private truth.
        x = x0 + (0.25 + 0.5 * alpha) * (x1 - x0)
        y = y0 + ((j * 0.61803398875) % 1.0) * (y1 - y0)
        z = z0 + (0.2 + 0.6 * ((j * 0.41421356237) % 1.0)) * (z1 - z0)
        vx = 1.0 + 0.15 * (j % 4); vy = (-1) ** j * (0.2 + 0.05 * (j % 3)); vz = 0.03 * ((j % 3) - 1)
        rows.append(Track(
            track_id=f"vtrack-{j+1:04d}", t=0.0,
            position=(x, y, z), velocity=(vx, vy, vz),
            covariance=((1.0,0.0,0.0),(0.0,1.0,0.0),(0.0,0.0,1.0)),
            last_seen_t=0.0, hits=10, status="confirmed",
            device_ids=(devices[j % len(devices)],), measured=True,
        ))
    return tuple(rows)


def benchmark_case(cfg, target_count: int, search_candidates_per_device: int,
                   repetitions: int = 3) -> dict:
    local = copy.deepcopy(cfg)
    planning = local.policy.setdefault("research", {}).setdefault("planning", {})
    planning["search_candidates_per_device"] = int(search_candidates_per_device)
    world = SimulationWorld(local)
    positions = _search_grid(local)
    ages = np.linspace(5.0, 60.0, len(positions), dtype=float)
    states = world.states()
    context = PolicyContext(
        t=0.0, dt=1/float(local.system.get("rate_hz", 10)), step=0,
        devices=states, tracks=_tracks(local, int(target_count)),
        research={
            "mission": "search_monitor",
            "search": {"positions_m": positions, "ages_s": ages,
                       "observed_now": np.zeros(len(positions), dtype=np.int8)},
            "readiness": {key: {"sensing_valid": True, "stable_since": 0.0, "reason": "ready"}
                          for key in states},
        },
    )
    generation_ms = []; solve_ms = []; statuses = []; timeouts = []
    candidate_count = overlap_count = None
    for _ in range(max(1, int(repetitions))):
        factory = _ConfigurableExecutionFactory(local)
        t0 = time.perf_counter(); ps = factory.generate(context)
        generation_ms.append((time.perf_counter()-t0)*1000.0)
        candidate_count = len(ps.flat); overlap_count = len(ps.overlap_requirements)
        solver = PriorityHorizonMILP(ps,
            float(planning.get("solver_time_limit_s", 0.12)),
            float(planning.get("solver_mip_rel_gap", 0.001)))
        _, diag = solver.solve_lexicographic("ecprh_scalability")
        solve_ms.append(float(diag.solve_ms)); statuses.append(diag.status); timeouts.append(bool(diag.timeout))
    return {
        "device_count": len(local.active_devices),
        "target_count": int(target_count),
        "search_candidates_per_device": int(search_candidates_per_device),
        "candidate_count": int(candidate_count or 0),
        "overlap_requirement_count": int(overlap_count or 0),
        "horizon_steps": int(math.ceil(float(planning.get("horizon_s",3.0))/float(planning.get("slot_s",0.5)))),
        "generation_ms_mean": float(np.mean(generation_ms)),
        "generation_ms_p95": float(np.percentile(generation_ms,95)),
        "solve_ms_mean": float(np.mean(solve_ms)),
        "solve_ms_p95": float(np.percentile(solve_ms,95)),
        "timeout_rate": float(np.mean(timeouts)),
        "statuses": "|".join(statuses),
        "repetitions": max(1, int(repetitions)),
    }


def run_scalability(config, target_counts=(0,1,2,3,4,5,6,8),
                    search_candidates=(4,8,12), repetitions=3,
                    output="runs/scalability.csv"):
    cfg = load_config(config)
    rows = [benchmark_case(cfg, j, k, repetitions)
            for j in target_counts for k in search_candidates]
    path = Path(output).resolve(); path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Benchmark ECP-RH planning scalability")
    parser.add_argument("--config", default="configs/research/search_monitor_base.yaml")
    parser.add_argument("--targets", nargs="+", type=int, default=[0,1,2,3,4,5,6,8])
    parser.add_argument("--search-candidates", nargs="+", type=int, default=[4,8,12])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", default="runs/scalability.csv")
    args = parser.parse_args(argv)
    print(run_scalability(args.config, args.targets, args.search_candidates,
                          args.repetitions, args.output))


if __name__ == "__main__":
    main()
