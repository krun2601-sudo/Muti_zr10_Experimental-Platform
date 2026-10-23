from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

_METADATA = {"scenario", "seed", "environment_seed", "network_seed", "method", "run_dir", "status", "config"}


def _read(path: Path) -> list[dict]:
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
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def aggregate_learning_replicates(rows: list[dict], *, expected_network_seeds,
                                  method="mappo") -> tuple[list[dict], list[dict]]:
    """Collapse network-seed replicas before paired environment-seed statistics.

    One paper-level MAPPO observation is one ``scenario x environment_seed`` case,
    not one trained network. Every case must contain exactly the same frozen network
    seeds. Numeric metrics are averaged over network replicas inside the case.
    Training-seed variability is reported separately and never increases the paired
    sample size used against ECP-RH or another deterministic/model-based method.
    """
    expected = tuple(sorted(int(x) for x in expected_network_seeds))
    if not expected:
        raise ValueError("expected_network_seeds cannot be empty")

    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for raw in rows:
        scenario = str(raw.get("scenario", ""))
        env_value = raw.get("environment_seed", raw.get("seed"))
        network_value = raw.get("network_seed")
        if not scenario or env_value is None or network_value is None:
            raise ValueError("learning replica rows require scenario, environment seed and network_seed")
        groups[(scenario, int(env_value))].append(raw)
    if not groups:
        raise ValueError("no learning replica rows")

    means = []
    variability = []
    for (scenario, env_seed), group in sorted(groups.items()):
        network_seeds = tuple(sorted(int(row["network_seed"]) for row in group))
        if network_seeds != expected:
            raise ValueError(
                f"{scenario}/{env_seed}: network seeds {network_seeds} != expected {expected}")
        if len(network_seeds) != len(set(network_seeds)):
            raise ValueError(f"{scenario}/{env_seed}: duplicate network-seed replica")

        numeric_keys = sorted({
            key for row in group for key, value in row.items()
            if key not in _METADATA and _number(value) is not None
        })
        mean_row = {
            "scenario": scenario,
            "seed": int(env_seed),
            "method": str(method),
            "network_replica_count": len(expected),
            "network_seeds": ",".join(map(str, expected)),
            "aggregation": "mean_over_network_seeds_within_environment_case",
        }
        for key in numeric_keys:
            values = np.asarray([_number(row.get(key)) for row in group], dtype=object)
            finite = np.asarray([float(x) for x in values if x is not None], dtype=float)
            if len(finite) != len(group):
                raise ValueError(f"{scenario}/{env_seed}: metric {key} missing for one or more replicas")
            mean_row[key] = float(finite.mean())
            variability.append({
                "scenario": scenario,
                "environment_seed": int(env_seed),
                "metric": key,
                "network_replica_count": len(finite),
                "network_seed_mean": float(finite.mean()),
                "network_seed_std": float(finite.std(ddof=1)) if len(finite) > 1 else 0.0,
                "network_seed_min": float(finite.min()),
                "network_seed_max": float(finite.max()),
            })
        means.append(mean_row)
    return means, variability


def aggregate_learning_csv(input_csv: str | Path, output_dir: str | Path,
                           *, expected_network_seeds, method="mappo") -> tuple[Path, Path]:
    rows = _read(Path(input_csv))
    means, variability = aggregate_learning_replicates(
        rows, expected_network_seeds=expected_network_seeds, method=method)
    output = Path(output_dir)
    means_path = output / f"{method}_environment_means.csv"
    variability_path = output / f"{method}_training_seed_variability.csv"
    _write(means_path, means)
    _write(variability_path, variability)
    return means_path, variability_path


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Average MAPPO network-seed replicas within each environment case")
    parser.add_argument("input_csv")
    parser.add_argument("--output", required=True)
    parser.add_argument("--network-seeds", nargs="+", type=int, required=True)
    parser.add_argument("--method", default="mappo")
    args = parser.parse_args(argv)
    paths = aggregate_learning_csv(
        args.input_csv, args.output,
        expected_network_seeds=args.network_seeds, method=args.method)
    print("\n".join(map(str, paths)))


if __name__ == "__main__":
    main()
