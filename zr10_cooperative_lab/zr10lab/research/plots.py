from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


PRIMARY = (
    "research_missed_target_rate",
    "research_detection_delay_censored_p95_s",
    "research_total_loss_s",
    "research_max_loss_gap_s",
    "research_revisit_age_p95_s",
)

LABELS = {
    "research_missed_target_rate": "Missed-target rate",
    "research_detection_delay_censored_p95_s": "Censored detection delay P95 / s",
    "research_total_loss_s": "Post-discovery total loss / s",
    "research_max_loss_gap_s": "Maximum monitoring gap / s",
    "research_revisit_age_p95_s": "Revisit age P95 / s",
}


def _read(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({k for row in rows for k in row})
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def comparison_figures(batch_dir: str | Path, output: str | Path | None = None):
    """Generate one independent figure per primary metric from saved summary CSV only."""
    batch_dir = Path(batch_dir).resolve()
    output = Path(output or batch_dir / "figures").resolve(); output.mkdir(parents=True, exist_ok=True)
    rows = _read(batch_dir / "summary_long.csv")
    if not rows:
        raise ValueError(f"summary_long.csv missing or empty under {batch_dir}")
    generated = []
    for metric in PRIMARY:
        data = [r for r in rows if r.get("metric") == metric]
        if not data:
            continue
        scenarios = sorted({r["scenario"] for r in data})
        methods = sorted({r["method"] for r in data})
        x = np.arange(len(scenarios), dtype=float)
        width = 0.8 / max(len(methods), 1)
        fig, ax = plt.subplots(figsize=(max(7, 1.2 * len(scenarios)), 4.6))
        figure_rows = []
        for i, method in enumerate(methods):
            means, lows, highs = [], [], []
            for scenario in scenarios:
                row = next((r for r in data if r["scenario"] == scenario and r["method"] == method), None)
                if row is None:
                    means.append(np.nan); lows.append(0.0); highs.append(0.0)
                    continue
                mean = float(row["mean"]); low = float(row["ci95_low"]); high = float(row["ci95_high"])
                means.append(mean); lows.append(max(0.0, mean-low)); highs.append(max(0.0, high-mean))
                figure_rows.append({"scenario": scenario, "method": method, "metric": metric,
                                    "mean": mean, "ci95_low": low, "ci95_high": high,
                                    "n": row.get("n", "")})
            positions = x - 0.4 + width/2 + i*width
            ax.errorbar(positions, means, yerr=np.asarray([lows, highs]), fmt="o", capsize=3, label=method)
        ax.set_xticks(x, scenarios, rotation=25, ha="right")
        ax.set_ylabel(LABELS.get(metric, metric))
        ax.grid(axis="y", alpha=0.25)
        ax.legend(fontsize=8, ncol=max(1, min(4, len(methods))))
        fig.tight_layout()
        png = output / f"comparison_{metric}.png"
        fig.savefig(png, dpi=220); plt.close(fig)
        _write(output / f"comparison_{metric}_data.csv", figure_rows)
        generated.append(str(png))
    return generated


def paired_advantage_figures(batch_dir: str | Path, output: str | Path | None = None):
    """Plot overall paired ECP-RH advantage; positive values always favor reference."""
    batch_dir = Path(batch_dir).resolve()
    output = Path(output or batch_dir / "figures").resolve(); output.mkdir(parents=True, exist_ok=True)
    rows = _read(batch_dir / "paired_comparisons.csv")
    generated = []
    for metric in PRIMARY:
        data = [row for row in rows if row.get("scope") == "overall" and row.get("metric") == metric]
        figure_rows = []
        for row in data:
            mean = _number(row.get("paired_mean_reference_advantage"))
            low = _number(row.get("bootstrap95_low")); high = _number(row.get("bootstrap95_high"))
            if mean is None:
                continue
            figure_rows.append({
                "competitor": row.get("competitor", ""), "metric": metric,
                "reference": row.get("reference", "ecprh"), "advantage": mean,
                "ci95_low": low, "ci95_high": high, "n_pairs": row.get("n_pairs", ""),
                "holm_adjusted_p": row.get("holm_adjusted_p", ""),
            })
        if not figure_rows:
            continue
        y = np.arange(len(figure_rows))
        values = np.asarray([r["advantage"] for r in figure_rows])
        lowerr = np.asarray([max(0.0, r["advantage"]-r["ci95_low"]) if r["ci95_low"] is not None else 0.0 for r in figure_rows])
        upperr = np.asarray([max(0.0, r["ci95_high"]-r["advantage"]) if r["ci95_high"] is not None else 0.0 for r in figure_rows])
        fig, ax = plt.subplots(figsize=(7.0, max(3.2, 0.55*len(figure_rows)+1.8)))
        ax.errorbar(values, y, xerr=np.asarray([lowerr, upperr]), fmt="o", capsize=3)
        ax.axvline(0.0, linewidth=1.0)
        ax.set_yticks(y, [r["competitor"] for r in figure_rows])
        ax.set_xlabel(f"Reference advantage: {LABELS.get(metric, metric)}")
        ax.grid(axis="x", alpha=0.25)
        fig.tight_layout()
        png = output / f"paired_{metric}.png"
        fig.savefig(png, dpi=220); plt.close(fig)
        _write(output / f"paired_{metric}_data.csv", figure_rows)
        generated.append(str(png))
    return generated


def tradeoff_figure(batch_dir: str | Path, output: str | Path | None = None):
    """Secondary visualization only; never replaces the ordered primary metrics."""
    batch_dir = Path(batch_dir).resolve()
    output = Path(output or batch_dir / "figures").resolve(); output.mkdir(parents=True, exist_ok=True)
    rows = _read(batch_dir / "run_metrics.csv")
    grouped = {}
    for r in rows:
        loss = _number(r.get("research_total_loss_s")); age = _number(r.get("research_revisit_age_p95_s"))
        if loss is None or age is None:
            continue
        grouped.setdefault(r["method"], []).append((loss, age))
    fig, ax = plt.subplots(figsize=(6.4, 4.8))
    out = []
    for method, values in sorted(grouped.items()):
        a = np.asarray(values, dtype=float)
        loss, age = float(a[:,0].mean()), float(a[:,1].mean())
        ax.scatter([loss], [age], label=method)
        ax.annotate(method, (loss, age), xytext=(4,4), textcoords="offset points", fontsize=8)
        out.append({"method": method, "mean_total_loss_s": loss, "mean_revisit_p95_s": age, "n": len(a)})
    ax.set_xlabel("Mean post-discovery monitoring loss / s")
    ax.set_ylabel("Mean P95 revisit age / s")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    png = output / "tradeoff_loss_vs_revisit.png"
    fig.savefig(png, dpi=220); plt.close(fig)
    _write(output / "tradeoff_loss_vs_revisit_data.csv", out)
    return png


def solver_figure(batch_dir: str | Path, output: str | Path | None = None):
    batch_dir = Path(batch_dir).resolve()
    output = Path(output or batch_dir / "figures").resolve(); output.mkdir(parents=True, exist_ok=True)
    rows = _read(batch_dir / "run_metrics.csv")
    data = []
    for row in rows:
        if row.get("method") not in ("ecprh", "weighted_rh"):
            continue
        solve = _number(row.get("solve_ms_p95"))
        if solve is None:
            continue
        data.append({"scenario": row.get("scenario", ""), "method": row.get("method", ""),
                     "seed": row.get("seed", ""), "solve_ms_p95": solve,
                     "solver_timeout_rate": _number(row.get("solver_timeout_rate")),
                     "visibility_level_certification_rate": _number(row.get("visibility_level_certification_rate")),
                     "priority_certification_rate": _number(row.get("priority_certification_rate"))})
    if not data:
        return None
    methods = sorted({row["method"] for row in data})
    values = [[r["solve_ms_p95"] for r in data if r["method"] == method] for method in methods]
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    ax.boxplot(values, tick_labels=methods, showfliers=False)
    ax.set_ylabel("Per-run solver-time P95 / ms")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    png = output / "solver_runtime.png"
    fig.savefig(png, dpi=220); plt.close(fig)
    _write(output / "solver_runtime_data.csv", data)
    return png


def run_timeline(run_dir: str | Path, output: str | Path | None = None):
    """Plot one recorded run without rerunning the algorithm."""
    run_dir = Path(run_dir).resolve()
    output = Path(output or run_dir / "figures").resolve(); output.mkdir(parents=True, exist_ok=True)
    cycles = _read(run_dir / "cycles.csv")
    timeline = []
    for row in cycles:
        try:
            metrics = json.loads(row.get("metrics_json") or "{}")
            timeline.append({"t_s": float(row["t_s"]), **metrics})
        except (ValueError, json.JSONDecodeError):
            continue
    if not timeline:
        return []
    generated = []
    definitions = [
        ("research_monitor_visible_ratio", "Visible ratio"),
        ("research_revisit_age_p95_s", "P95 revisit age / s"),
        ("research_sensing_duty_cycle", "Sensing duty cycle"),
        ("research_empirical_risk_violation_rate", "Empirical risk violation rate"),
    ]
    for key, ylabel in definitions:
        points = [(r["t_s"], r.get(key)) for r in timeline if isinstance(r.get(key), (int, float))]
        if not points:
            continue
        a = np.asarray(points, dtype=float)
        fig, ax = plt.subplots(figsize=(7.0, 3.8))
        ax.plot(a[:,0], a[:,1])
        ax.set_xlabel("Time / s"); ax.set_ylabel(ylabel); ax.grid(alpha=0.25)
        fig.tight_layout()
        png = output / f"timeline_{key}.png"
        fig.savefig(png, dpi=220); plt.close(fig)
        _write(output / f"timeline_{key}_data.csv",
               [{"t_s": float(t), key: float(v)} for t, v in points])
        generated.append(str(png))
    return generated


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate paper figures from saved research CSV files")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("batch"); p.add_argument("batch_dir"); p.add_argument("--output")
    p = sub.add_parser("run"); p.add_argument("run_dir"); p.add_argument("--output")
    args = parser.parse_args(argv)
    if args.command == "batch":
        files = comparison_figures(args.batch_dir, args.output)
        files += paired_advantage_figures(args.batch_dir, args.output)
        files.append(str(tradeoff_figure(args.batch_dir, args.output)))
        solver = solver_figure(args.batch_dir, args.output)
        if solver is not None:
            files.append(str(solver))
    else:
        files = run_timeline(args.run_dir, args.output)
    print("\n".join(files))


if __name__ == "__main__":
    main()
