from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from .plots import PRIMARY, LABELS


def _read(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def _number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _mean_ci(values, *, resamples: int = 10000, seed: int = 20261024):
    """Return mean and a deterministic percentile-bootstrap 95% CI.

    Ablation inputs are paired differences before reaching this function, so the
    interval is a paired bootstrap over scenario/seed cases. Sensitivity panels use
    the same reproducible bootstrap for descriptive mean intervals. No experiment
    outputs are changed; this function only affects visualization uncertainty bands.
    """
    a = np.asarray([v for v in values if v is not None and math.isfinite(float(v))], dtype=float)
    if not len(a):
        return None
    mean = float(a.mean())
    if len(a) == 1:
        return mean, mean, mean, 1
    rng = np.random.default_rng(int(seed))
    draws = rng.choice(a, size=(max(1, int(resamples)), len(a)), replace=True).mean(axis=1)
    low, high = np.percentile(draws, [2.5, 97.5])
    return mean, float(low), float(high), len(a)


def ablation_figures(root: str | Path, output: str | Path | None = None):
    """Create per-scenario relative-degradation figures from paired ablation runs.

    Positive degradation means the ablated model is worse than ``ecprh[full]`` for
    every primary metric (all primary metrics are minimized). No cross-scenario
    averaging is used because each ablation is tied to a predeclared mechanism and
    scenario family. Error bars are percentile-bootstrap intervals over paired
    scenario/seed differences.
    """
    root = Path(root).resolve()
    output = Path(output or root / "figures").resolve(); output.mkdir(parents=True, exist_ok=True)
    rows = _read(root / "run_metrics.csv")
    if not rows:
        raise ValueError(f"run_metrics.csv missing under {root}")
    generated = []
    scenarios = sorted({r.get("scenario", "") for r in rows})
    for scenario in scenarios:
        sr = [r for r in rows if r.get("scenario") == scenario]
        methods = sorted({r.get("method", "") for r in sr})
        if "ecprh[full]" not in methods:
            continue
        variants = [m for m in methods if m != "ecprh[full]"]
        if not variants:
            continue
        lookup = {(r.get("seed"), r.get("method")): r for r in sr}
        for metric in PRIMARY:
            figure_rows=[]
            for variant in variants:
                diffs=[]
                for seed in sorted({r.get("seed") for r in sr}):
                    full=lookup.get((seed,"ecprh[full]")); abl=lookup.get((seed,variant))
                    if full is None or abl is None: continue
                    fv=_number(full.get(metric)); av=_number(abl.get(metric))
                    if fv is None or av is None: continue
                    diffs.append(av-fv)
                stats=_mean_ci(diffs)
                if stats is None: continue
                mean,low,high,n=stats
                figure_rows.append({"scenario":scenario,"metric":metric,"variant":variant,
                                    "mean_degradation":mean,"ci95_low":low,"ci95_high":high,"n_pairs":n,
                                    "ci_method":"paired_percentile_bootstrap_10000"})
            if not figure_rows: continue
            x=np.arange(len(figure_rows)); y=np.asarray([r["mean_degradation"] for r in figure_rows])
            lo=np.asarray([max(0.0,r["mean_degradation"]-r["ci95_low"]) for r in figure_rows])
            hi=np.asarray([max(0.0,r["ci95_high"]-r["mean_degradation"]) for r in figure_rows])
            fig,ax=plt.subplots(figsize=(max(6.4,0.9*len(figure_rows)+2.5),4.2))
            ax.errorbar(x,y,yerr=np.asarray([lo,hi]),fmt="o",capsize=3)
            ax.axhline(0.0,linewidth=1.0)
            ax.set_xticks(x,[r["variant"].replace("ecprh[","").rstrip("]") for r in figure_rows],rotation=25,ha="right")
            ax.set_ylabel(f"Ablation degradation: {LABELS.get(metric,metric)}")
            ax.set_title(scenario); ax.grid(axis="y",alpha=0.25); fig.tight_layout()
            stem=f"ablation_{re.sub(r'[^A-Za-z0-9_-]+','_',scenario)}_{metric}"
            png=output/f"{stem}.png"; fig.savefig(png,dpi=220); plt.close(fig)
            _write(output/f"{stem}_data.csv",figure_rows); generated.append(str(png))
    return generated


def _parse_sensitivity_method(method: str):
    match=re.fullmatch(r"ecprh\[(.+)=(.+)\]",str(method))
    if not match: return None
    path,value=match.groups()
    try: numeric=float(value)
    except ValueError: return None
    return path,numeric


def sensitivity_figures(root: str | Path, output: str | Path | None = None):
    """Plot sensitivity means with reproducible bootstrap 95% intervals."""
    root=Path(root).resolve(); output=Path(output or root/"figures").resolve();output.mkdir(parents=True,exist_ok=True)
    rows=_read(root/"run_metrics.csv")
    if not rows: raise ValueError(f"run_metrics.csv missing under {root}")
    parsed=[]
    for r in rows:
        p=_parse_sensitivity_method(r.get("method",""))
        if p is not None: parsed.append((r,p[0],p[1]))
    paths=sorted({path for _,path,_ in parsed}); generated=[]
    for path in paths:
        pr=[(r,value) for r,p,value in parsed if p==path]
        values=sorted({value for _,value in pr})
        scenarios=sorted({r.get("scenario","") for r,_ in pr})
        for metric in PRIMARY:
            figure_rows=[]
            fig,ax=plt.subplots(figsize=(6.4,4.2))
            has=False
            for scenario in scenarios:
                means=[]; lows=[]; highs=[]; xs=[]
                for value in values:
                    vals=[_number(r.get(metric)) for r,v in pr if r.get("scenario")==scenario and v==value]
                    stats=_mean_ci(vals)
                    if stats is None: continue
                    mean,low,high,n=stats;xs.append(value);means.append(mean);lows.append(low);highs.append(high)
                    figure_rows.append({"parameter":path,"value":value,"scenario":scenario,"metric":metric,
                                        "mean":mean,"ci95_low":low,"ci95_high":high,"n":n,
                                        "ci_method":"percentile_bootstrap_10000"})
                if xs:
                    has=True
                    y=np.asarray(means); lo=np.maximum(0,y-np.asarray(lows)); hi=np.maximum(0,np.asarray(highs)-y)
                    ax.errorbar(xs,y,yerr=np.asarray([lo,hi]),marker="o",capsize=3,label=scenario)
            if not has:
                plt.close(fig); continue
            ax.set_xlabel(path.split(".")[-1]);ax.set_ylabel(LABELS.get(metric,metric));ax.grid(alpha=0.25);ax.legend(fontsize=8)
            fig.tight_layout(); short=path.split(".")[-1]
            png=output/f"sensitivity_{short}_{metric}.png";fig.savefig(png,dpi=220);plt.close(fig)
            _write(output/f"sensitivity_{short}_{metric}_data.csv",figure_rows);generated.append(str(png))
    return generated


def scalability_figures(csv_path: str | Path, output: str | Path | None = None):
    """Generate scalability figures strictly from the frozen benchmark CSV.

    Candidate generation and MILP solution times are plotted separately because the
    frozen benchmark shows that geometry/candidate construction, not HiGHS, becomes
    the dominant high-target-count bottleneck.
    """
    csv_path=Path(csv_path).resolve(); output=Path(output or csv_path.parent/"figures").resolve();output.mkdir(parents=True,exist_ok=True)
    rows=_read(csv_path)
    if not rows: raise ValueError(f"empty scalability table: {csv_path}")
    generated=[]
    definitions=[
        ("generation_ms_p95","Candidate generation P95 / ms"),
        ("solve_ms_p95","MILP solve P95 / ms"),
        ("candidate_count","Candidate count"),
        ("priority_certification_rate","Priority certification rate"),
    ]
    candidate_levels=sorted({int(float(r["search_candidates_per_device"])) for r in rows})
    for key,ylabel in definitions:
        fig,ax=plt.subplots(figsize=(6.4,4.2));source=[];has=False
        for level in candidate_levels:
            data=sorted((int(float(r["target_count"])),_number(r.get(key))) for r in rows
                        if int(float(r["search_candidates_per_device"]))==level)
            data=[x for x in data if x[1] is not None]
            if not data: continue
            has=True;x=[a for a,_ in data];y=[b for _,b in data]
            ax.plot(x,y,marker="o",label=f"search candidates/device={level}")
            source.extend({"target_count":a,"search_candidates_per_device":level,key:b} for a,b in data)
        if not has:
            plt.close(fig);continue
        ax.set_xlabel("Target count");ax.set_ylabel(ylabel);ax.grid(alpha=0.25);ax.legend(fontsize=8);fig.tight_layout()
        png=output/f"scalability_{key}.png";fig.savefig(png,dpi=220);plt.close(fig)
        _write(output/f"scalability_{key}_data.csv",source);generated.append(str(png))
    return generated


def main(argv=None):
    parser=argparse.ArgumentParser(description="Generate paper study figures from frozen CSV outputs")
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("ablation");p.add_argument("root");p.add_argument("--output")
    p=sub.add_parser("sensitivity");p.add_argument("root");p.add_argument("--output")
    p=sub.add_parser("scalability");p.add_argument("csv");p.add_argument("--output")
    args=parser.parse_args(argv)
    if args.command=="ablation": files=ablation_figures(args.root,args.output)
    elif args.command=="sensitivity": files=sensitivity_figures(args.root,args.output)
    else: files=scalability_figures(args.csv,args.output)
    print("\n".join(files))


if __name__=="__main__":
    main()
