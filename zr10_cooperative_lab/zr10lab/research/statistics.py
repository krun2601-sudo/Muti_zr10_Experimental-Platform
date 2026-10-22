from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon


DEFAULT_DIRECTIONS = {
    "research_missed_target_rate": "minimize",
    "research_detection_delay_censored_mean_s": "minimize",
    "research_detection_delay_censored_p95_s": "minimize",
    "research_total_loss_s": "minimize",
    "research_max_loss_gap_s": "minimize",
    "research_detection_delay_mean_s": "minimize",
    "research_detection_delay_p95_s": "minimize",
    "research_revisit_age_p95_s": "minimize",
    "research_search_age_integral": "minimize",
    "research_monitor_visible_ratio": "maximize",
    "research_discovery_rate": "maximize",
    "research_handover_success_rate": "maximize",
    "research_empirical_risk_violation_rate": "minimize",
    "research_sensing_duty_cycle": "maximize",
    "research_total_yaw_motion_deg": "minimize",
    "research_total_pitch_motion_deg": "minimize",
    "research_total_zoom_change": "minimize",
    "research_assignment_switch_count": "minimize",
    "solve_ms_p95": "minimize",
    "solver_timeout_rate": "minimize",
}


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write(path: Path, rows: list[dict]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _bootstrap_mean_ci(values: np.ndarray, samples: int, rng) -> tuple[float, float]:
    if len(values) == 1:
        return float(values[0]), float(values[0])
    means = np.empty(samples, dtype=float)
    chunk = 1000
    for start in range(0, samples, chunk):
        n = min(chunk, samples - start)
        indices = rng.integers(0, len(values), size=(n, len(values)))
        means[start:start+n] = values[indices].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _holm(rows: list[dict]) -> None:
    """Holm adjust p-values within each declared statistical family."""
    groups = {}
    for i, row in enumerate(rows):
        p = row.get("wilcoxon_p")
        if p is not None and math.isfinite(float(p)):
            family = (row.get("scope", "overall"), row.get("scenario", "__all__"), row["metric"])
            groups.setdefault(family, []).append((i, float(p)))
    for items in groups.values():
        ordered = sorted(items, key=lambda item: item[1])
        m = len(ordered)
        adjusted_running = 0.0
        for rank, (index, p) in enumerate(ordered):
            adjusted_running = max(adjusted_running, (m - rank) * p)
            rows[index]["holm_adjusted_p"] = min(1.0, adjusted_running)


def _comparison_row(values, raw_differences, *, metric, direction, reference,
                    competitor, scope, scenario, bootstrap_samples, rng):
    if not values:
        return None
    values = np.asarray(values, dtype=float)
    ci_low, ci_high = _bootstrap_mean_ci(values, int(bootstrap_samples), rng)
    nonzero = np.asarray(raw_differences, dtype=float)
    if len(nonzero) < 2 or np.all(np.abs(nonzero) < 1e-12):
        p = 1.0
    else:
        try:
            p = float(wilcoxon(nonzero, zero_method="wilcox", alternative="two-sided").pvalue)
        except ValueError:
            p = 1.0
    return {
        "scope": scope,
        "scenario": scenario,
        "metric": metric,
        "direction": direction,
        "reference": reference,
        "competitor": competitor,
        "n_pairs": len(values),
        "paired_mean_reference_advantage": float(values.mean()),
        "paired_median_reference_advantage": float(np.median(values)),
        "bootstrap95_low": ci_low,
        "bootstrap95_high": ci_high,
        "reference_win_rate": float(np.mean(values > 0)),
        "tie_rate": float(np.mean(np.abs(values) <= 1e-12)),
        "wilcoxon_p": p,
        "holm_adjusted_p": None,
    }


def paired_comparisons(run_metrics_csv: str | Path, output_csv: str | Path,
                       reference="ecprh", directions=None,
                       bootstrap_samples=10000, seed=20261022,
                       include_per_scenario=True) -> list[dict]:
    """Compare each method with reference using identical scenario/seed pairs.

    ``reference_advantage`` is oriented so positive always favors the reference:
    competitor-reference for minimized metrics and reference-competitor for
    maximized metrics. Failed/missing runs are never imputed; reported ``n_pairs``
    makes the available evidence explicit.  The output contains an overall paired
    analysis plus per-scenario analyses so a favorable global average cannot hide a
    failure in a specific handoff, overload, or OOD regime.
    """
    directions = {**DEFAULT_DIRECTIONS, **(directions or {})}
    raw = _read(Path(run_metrics_csv))
    by_key = {}
    methods = set()
    scenarios = set()
    for row in raw:
        method = row.get("method")
        scenario = row.get("scenario")
        seed_value = row.get("seed")
        if not method or scenario is None or seed_value is None:
            continue
        methods.add(method); scenarios.add(str(scenario))
        by_key[(str(scenario), str(seed_value), method)] = row

    results = []
    rng = np.random.default_rng(seed)
    scopes = [("overall", "__all__", None)]
    if include_per_scenario:
        scopes.extend(("scenario", scenario, scenario) for scenario in sorted(scenarios))

    for scope, scenario_label, scenario_filter in scopes:
        for metric, direction in directions.items():
            if direction not in ("minimize", "maximize"):
                continue
            for competitor in sorted(methods - {reference}):
                advantages = []
                raw_differences = []
                for (scenario, seed_text, method), ref_row in by_key.items():
                    if method != reference or (scenario_filter is not None and scenario != scenario_filter):
                        continue
                    other = by_key.get((scenario, seed_text, competitor))
                    if other is None:
                        continue
                    ref = _number(ref_row.get(metric)); comp = _number(other.get(metric))
                    if ref is None or comp is None:
                        continue
                    raw_differences.append(ref - comp)
                    advantages.append(comp - ref if direction == "minimize" else ref - comp)
                row = _comparison_row(
                    advantages, raw_differences,
                    metric=metric, direction=direction, reference=reference,
                    competitor=competitor, scope=scope, scenario=scenario_label,
                    bootstrap_samples=bootstrap_samples, rng=rng,
                )
                if row is not None:
                    results.append(row)
    _holm(results)
    _write(Path(output_csv), results)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Paired Monte Carlo comparison against a reference method")
    parser.add_argument("run_metrics_csv")
    parser.add_argument("--reference", default="ecprh")
    parser.add_argument("--output", default="paired_comparisons.csv")
    parser.add_argument("--bootstrap", type=int, default=10000)
    parser.add_argument("--overall-only", action="store_true")
    args = parser.parse_args(argv)
    rows = paired_comparisons(args.run_metrics_csv, args.output, args.reference,
                              bootstrap_samples=args.bootstrap,
                              include_per_scenario=not args.overall_only)
    print(f"wrote {len(rows)} paired comparison rows to {args.output}")


if __name__ == "__main__":
    main()
