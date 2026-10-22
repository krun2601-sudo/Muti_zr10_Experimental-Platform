from __future__ import annotations

import argparse
import copy
import itertools
import json
from pathlib import Path

import numpy as np
import yaml

from ..config import load_config
from .batch import _last_cycle_metrics, _write_table
from .runner import run_research_simulation


SELECTION_METRICS = (
    "research_total_loss_s",
    "research_max_loss_gap_s",
    "research_revisit_age_p95_s",
    "research_detection_delay_p95_s",
)


def _metric(value):
    return float(value) if isinstance(value, (int, float)) and np.isfinite(value) else float("inf")


def _score(summary):
    return tuple(_metric(summary.get(key)) for key in SELECTION_METRICS)


def _budgeted_combinations(method, validation_configs, keys, values,
                           max_combinations: int | None, sample_seed: int):
    all_rows=list(itertools.product(*values))
    if not max_combinations or len(all_rows)<=int(max_combinations):
        return all_rows
    budget=max(1,int(max_combinations))
    rng=np.random.default_rng(int(sample_seed))
    chosen=set()
    # Always include the declared default parameter tuple when every default lies
    # inside the grid. This makes "no tuning" a candidate under the same budget.
    cfg=load_config(validation_configs[0])
    default=cfg.policy.get("research",{}).get("baselines",{}).get(method,{})
    default_tuple=tuple(default.get(key) for key in keys)
    try:
        default_index=all_rows.index(default_tuple)
        chosen.add(default_index)
    except ValueError:
        pass
    remaining=[i for i in range(len(all_rows)) if i not in chosen]
    take=min(len(remaining),budget-len(chosen))
    if take>0:
        chosen.update(int(i) for i in rng.choice(remaining,size=take,replace=False))
    return [all_rows[i] for i in sorted(chosen)]


def tune_baseline(method, validation_configs, seeds, grid: dict[str, list], output,
                  max_combinations=24, sample_seed=20261022):
    """Tune one parameterized baseline using a common validation-only budget.

    Every parameterized baseline uses the same maximum number of candidate
    parameter settings and the same lexicographic task metric selection rule.
    Large Cartesian grids are deterministically subsampled with a fixed seed; the
    currently declared default is included whenever it belongs to the grid.
    """
    if not grid:
        raise ValueError("baseline grid must contain at least one parameter")
    keys=list(grid); values=[list(grid[key]) for key in keys]
    combinations=_budgeted_combinations(method,validation_configs,keys,values,
                                         max_combinations,sample_seed)
    root=Path(output).resolve(); root.mkdir(parents=True,exist_ok=True)
    rows=[]; summaries=[]
    for combination in combinations:
        params=dict(zip(keys,combination)); collected=[]
        for config_path in validation_configs:
            for seed in seeds:
                cfg=load_config(config_path)
                baseline=cfg.policy.setdefault("research",{}).setdefault("baselines",{}).setdefault(method,{})
                baseline.update(copy.deepcopy(params))
                run_dir=run_research_simulation(cfg,method,root/"runs",int(seed))
                metrics=_last_cycle_metrics(Path(run_dir)); collected.append(metrics)
                rows.append({"method":method,"config":str(Path(config_path).resolve()),"seed":int(seed),
                             **{f"param_{k}":v for k,v in params.items()},**metrics})
                _write_table(root/"tuning_runs.csv",rows)
        summary={"method":method,**{f"param_{k}":v for k,v in params.items()},"runs":len(collected)}
        for metric in SELECTION_METRICS:
            finite=[float(x[metric]) for x in collected if isinstance(x.get(metric),(int,float)) and np.isfinite(x[metric])]
            summary[metric]=float(np.mean(finite)) if finite else None
        summaries.append(summary); _write_table(root/"tuning_summary.csv",summaries)
    if not summaries: raise RuntimeError("no baseline parameter combinations were evaluated")
    selected=min(summaries,key=_score)
    selected_params={key:selected[f"param_{key}"] for key in keys}
    document={
        "method":method,
        "selection_rule":"lexicographic validation means: total loss, max gap, revisit P95, detection-delay P95",
        "selection_metrics":list(SELECTION_METRICS),
        "validation_configs":[str(Path(x).resolve()) for x in validation_configs],
        "validation_seeds":[int(x) for x in seeds],
        "full_grid_size":int(np.prod([len(v) for v in values])),
        "evaluated_parameter_count":len(combinations),
        "max_combinations":int(max_combinations) if max_combinations else None,
        "parameter_sample_seed":int(sample_seed),
        "grid":grid,
        "selected_params":selected_params,
        "selected_summary":selected,
    }
    path=root/f"selected_{method}.json"
    path.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding="utf-8")
    return path


def tune_from_manifest(manifest_path, method, output):
    manifest_path=Path(manifest_path).resolve()
    manifest=yaml.safe_load(manifest_path.read_text(encoding="utf-8-sig"))
    tuning=manifest.get("baseline_tuning",{}).get(method)
    if not isinstance(tuning,dict) or "grid" not in tuning:
        raise ValueError(f"manifest contains no generic tuning grid for {method!r}")
    split_name=str(tuning.get("split","validation_only"))
    if split_name in ("test_main","test_ood"):
        raise ValueError("test split cannot be used for baseline tuning")
    split=manifest.get("splits",{}).get(split_name)
    if not isinstance(split,dict): raise ValueError(f"unknown tuning split {split_name}")
    root=manifest_path.parent
    configs=[(root/Path(p)).resolve() for p in split.get("scenarios",[])]
    split_seeds=[int(x) for x in split.get("seeds",[])]
    requested=[int(x) for x in tuning.get("tuning_seeds",split_seeds)]
    if not set(requested).issubset(set(split_seeds)):
        raise ValueError("baseline tuning seeds must be a subset of the declared validation split")
    return tune_baseline(method,configs,requested,tuning["grid"],Path(output)/method,
                         max_combinations=tuning.get("max_combinations",24),
                         sample_seed=tuning.get("parameter_sample_seed",20261022))


def main(argv=None):
    parser=argparse.ArgumentParser(description="Tune a parameterized baseline on validation only")
    parser.add_argument("--manifest",default="configs/research/paper_experiment_manifest.yaml")
    parser.add_argument("--method",required=True,choices=["weighted_rh","classical_ptz","info_planner","ssm_belief"])
    parser.add_argument("--output",default="runs/baseline_tuning")
    args=parser.parse_args(argv)
    print(tune_from_manifest(args.manifest,args.method,args.output))


if __name__=="__main__":
    main()
