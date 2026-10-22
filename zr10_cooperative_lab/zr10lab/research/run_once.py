from __future__ import annotations

import argparse

from ..config import load_config
from .runner import run_research_simulation


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run one headless persistent-search experiment")
    parser.add_argument("--config", default="configs/research/search_monitor_base.yaml")
    parser.add_argument("--method", default="ecprh",
                        choices=("ecprh","weighted_rh","greedy","fixed_scan","classical_ptz",
                                 "info_planner","ssm_belief","mappo","safe_mappo"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", default="runs")
    parser.add_argument("--realtime", action="store_true")
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    path = run_research_simulation(cfg, args.method, args.output, args.seed, args.realtime)
    print(path)


if __name__ == "__main__":
    main()
