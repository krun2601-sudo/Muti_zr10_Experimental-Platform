from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

from .candidate_mappo import SELECTION_METRICS

_UPDATE_RE = re.compile(r"_u(\d+)\.pt$")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _update_from_checkpoint(value: str) -> int:
    match = _UPDATE_RE.search(Path(value).name)
    if not match:
        raise ValueError(f"cannot infer training update from checkpoint {value!r}")
    return int(match.group(1))


def _float(row: dict, key: str) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"missing/non-numeric validation metric {key!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"non-finite validation metric {key!r}: {value!r}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _score(row: dict) -> tuple[float, ...]:
    return tuple(float(row[key]) for key in SELECTION_METRICS)


def aggregate_common_update(seed_dirs: list[str | Path], output: str | Path,
                            expected_network_seeds: list[int] | None = None,
                            expected_validation_seeds: list[int] | None = None,
                            expected_scenarios: list[str] | None = None,
                            eligible_updates: list[int] | None = None,
                            expected_training_pairs: int | None = None,
                            minimum_uses_per_training_pair: int = 1) -> dict:
    """Select one training update shared by every MAPPO network replica.

    Each ``seed_dir`` must contain a ``train`` directory with checkpoint metadata
    and a ``select/validation_checkpoint_runs.csv`` table produced from the same
    frozen validation split. The function refuses incomplete/asymmetric inputs and
    never selects the best network seed. If training-coverage requirements are
    supplied, an update is eligible only when every replica checkpoint has actually
    used the complete frozen scenario x environment-seed training product at least
    the requested number of times.
    """
    roots = [Path(x).resolve() for x in seed_dirs]
    if len(roots) < 2:
        raise ValueError("formal multiseed selection requires at least two network-seed runs")
    if expected_training_pairs is not None and int(expected_training_pairs) < 1:
        raise ValueError("expected_training_pairs must be positive")
    if int(minimum_uses_per_training_pair) < 1:
        raise ValueError("minimum_uses_per_training_pair must be positive")

    runs_by_update: dict[int, list[dict]] = defaultdict(list)
    checkpoints_by_seed: dict[int, dict[int, Path]] = {}
    validation_keys_by_seed: dict[int, dict[int, set[tuple[str, int]]]] = {}
    metadata_by_seed_update: dict[tuple[int, int], dict] = {}
    implementations = set()

    for root in roots:
        train_indices = sorted((root / "train").glob("*training_index.json"))
        if len(train_indices) != 1:
            raise ValueError(f"{root}: expected exactly one training index, found {len(train_indices)}")
        index = json.loads(train_indices[0].read_text(encoding="utf-8"))
        network_seed = int(index["seed"])
        if network_seed in checkpoints_by_seed:
            raise ValueError(f"duplicate network seed {network_seed}")
        implementations.add(str(index.get("implementation", "")))

        checkpoints = {}
        for raw in index.get("checkpoints", []):
            checkpoint = Path(raw)
            if not checkpoint.is_absolute():
                checkpoint = (root / checkpoint).resolve() if not (root / raw).exists() else (root / raw).resolve()
            if not checkpoint.exists():
                # Common artifact layout stores paths relative to the original run
                # root. Fall back to matching by basename inside this seed artifact.
                matches = list(root.rglob(Path(raw).name))
                if len(matches) != 1:
                    raise ValueError(f"{root}: cannot uniquely resolve checkpoint {raw!r}")
                checkpoint = matches[0].resolve()
            update = _update_from_checkpoint(str(checkpoint))
            metadata = Path(str(checkpoint) + ".json")
            if not metadata.exists():
                raise ValueError(f"missing checkpoint metadata {metadata}")
            meta = json.loads(metadata.read_text(encoding="utf-8"))
            if int(meta.get("seed", -1)) != network_seed:
                raise ValueError(f"checkpoint seed mismatch for {checkpoint}")
            if int(meta.get("training_update", -1)) != update:
                raise ValueError(f"checkpoint update mismatch for {checkpoint}")
            checkpoints[update] = checkpoint
            metadata_by_seed_update[(network_seed, update)] = meta
        if not checkpoints:
            raise ValueError(f"{root}: no checkpoints found")
        checkpoints_by_seed[network_seed] = checkpoints

        table = root / "select" / "validation_checkpoint_runs.csv"
        if not table.exists():
            raise ValueError(f"{root}: missing {table.name}")
        keys_by_update: dict[int, set[tuple[str, int]]] = defaultdict(set)
        for raw in _read_csv(table):
            update = _update_from_checkpoint(raw["checkpoint"])
            scenario = str(raw.get("scenario") or raw.get("config") or "")
            seed = int(raw["seed"])
            key = (scenario, seed)
            if key in keys_by_update[update]:
                raise ValueError(f"{root}: duplicate validation run for update={update}, key={key}")
            keys_by_update[update].add(key)
            row = {"network_seed": network_seed, "update": update,
                   "scenario": scenario, "validation_seed": seed}
            for metric in SELECTION_METRICS:
                row[metric] = _float(raw, metric)
            runs_by_update[update].append(row)
        validation_keys_by_seed[network_seed] = dict(keys_by_update)

    seeds = sorted(checkpoints_by_seed)
    if expected_network_seeds is not None and seeds != sorted(map(int, expected_network_seeds)):
        raise ValueError(f"network seeds {seeds} != expected {sorted(map(int, expected_network_seeds))}")
    if len(implementations) != 1:
        raise ValueError(f"network replicas use different implementations: {sorted(implementations)}")

    update_sets = [set(checkpoints_by_seed[seed]) for seed in seeds]
    common_updates = set.intersection(*update_sets)
    if not common_updates or any(values != common_updates for values in update_sets):
        raise ValueError(f"checkpoint update sets differ across seeds: {dict(zip(seeds, map(sorted, update_sets)))}")

    if eligible_updates is not None:
        eligible = set(map(int, eligible_updates))
        if not eligible:
            raise ValueError("eligible_updates cannot be empty")
        if not eligible.issubset(common_updates):
            raise ValueError(
                f"eligible validation updates {sorted(eligible)} are not all available in {sorted(common_updates)}")
        candidate_updates = eligible
    else:
        candidate_updates = set(common_updates)

    reference_keys = None
    for network_seed in seeds:
        per_update = validation_keys_by_seed[network_seed]
        if set(per_update) != common_updates:
            raise ValueError(f"network seed {network_seed}: validation updates do not match checkpoint updates")
        for update in sorted(common_updates):
            keys = per_update[update]
            if reference_keys is None:
                reference_keys = set(keys)
            elif keys != reference_keys:
                raise ValueError(
                    f"network seed {network_seed}, update {update}: validation split differs from reference")

    reference_keys = reference_keys or set()
    if expected_validation_seeds is not None:
        seen = sorted({seed for _, seed in reference_keys})
        expected = sorted(map(int, expected_validation_seeds))
        if seen != expected:
            raise ValueError(f"validation seeds {seen} != expected {expected}")
    if expected_scenarios is not None:
        expected_tokens = [str(x) for x in expected_scenarios]
        seen_scenarios = sorted({scenario for scenario, _ in reference_keys})
        for token in expected_tokens:
            if not any(token in value for value in seen_scenarios):
                raise ValueError(f"expected validation scenario token {token!r} not found in {seen_scenarios}")

    # Apply the precommitted training-product coverage gate before looking at
    # validation scores. This prevents choosing a numerically attractive checkpoint
    # that has not actually seen the full training split.
    coverage_by_update: dict[int, dict[int, dict]] = {}
    valid_updates = []
    for update in sorted(candidate_updates):
        coverage_by_update[update] = {}
        valid = True
        for network_seed in seeds:
            meta = metadata_by_seed_update[(network_seed, update)]
            usage = {str(k): int(v) for k, v in dict(meta.get("episode_usage", {})).items()}
            count = len(usage)
            min_use = min(usage.values()) if usage else 0
            coverage_by_update[update][network_seed] = {
                "training_pair_count": count,
                "minimum_uses_per_pair": min_use,
                "episodes_started": int(meta.get("episodes_started", 0)),
            }
            if expected_training_pairs is not None and count != int(expected_training_pairs):
                valid = False
            if min_use < int(minimum_uses_per_training_pair):
                valid = False
        if valid:
            valid_updates.append(update)
    if not valid_updates:
        raise ValueError(
            "no common checkpoint update satisfies the frozen training-product coverage requirements")

    expected_count = len(seeds) * len(reference_keys)
    summary = []
    for update in sorted(valid_updates):
        rows = runs_by_update[update]
        if len(rows) != expected_count:
            raise ValueError(
                f"update {update}: expected {expected_count} validation rows, found {len(rows)}")
        item = {"update": int(update), "network_seed_count": len(seeds),
                "validation_cases_per_seed": len(reference_keys), "n": len(rows)}
        for metric in SELECTION_METRICS:
            values = np.asarray([float(row[metric]) for row in rows], dtype=float)
            item[metric] = float(values.mean())
            item[metric + "_std_all_runs"] = float(values.std(ddof=1)) if len(values) > 1 else 0.0
        summary.append(item)

    selected = min(summary, key=_score)
    selected_update = int(selected["update"])
    replicas = []
    for network_seed in seeds:
        checkpoint = checkpoints_by_seed[network_seed][selected_update]
        metadata = Path(str(checkpoint) + ".json")
        meta = metadata_by_seed_update[(network_seed, selected_update)]
        coverage = coverage_by_update[selected_update][network_seed]
        replicas.append({
            "network_seed": network_seed,
            "checkpoint": str(checkpoint),
            "checkpoint_sha256": _sha256(checkpoint),
            "metadata": str(metadata),
            "metadata_sha256": _sha256(metadata),
            "episodes_started": int(meta.get("episodes_started", 0)),
            "episode_usage_count": int(coverage["training_pair_count"]),
            "minimum_uses_per_training_pair": int(coverage["minimum_uses_per_pair"]),
        })

    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    result = {
        "implementation": next(iter(implementations)),
        "selection_rule": (
            "training-coverage-qualified common-update lexicographic mean across every "
            "network-seed x validation-case run; never select the best network seed"),
        "selection_metrics": list(SELECTION_METRICS),
        "network_seeds": seeds,
        "validation_cases": sorted([{"scenario": s, "seed": seed} for s, seed in reference_keys],
                                   key=lambda x: (x["scenario"], x["seed"])),
        "available_common_updates": sorted(common_updates),
        "precommitted_eligible_updates": sorted(candidate_updates),
        "coverage_qualified_updates": sorted(valid_updates),
        "training_coverage_requirements": {
            "expected_training_pairs": expected_training_pairs,
            "minimum_uses_per_training_pair": int(minimum_uses_per_training_pair),
        },
        "selected_update": selected_update,
        "selected_validation_summary": selected,
        "replicas": replicas,
    }
    (output / "formal_learning_selection.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = sorted({key for row in summary for key in row})
    with (output / "common_update_validation_summary.csv").open(
            "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(summary)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Select one MAPPO update shared by all network seeds")
    parser.add_argument("seed_dirs", nargs="+")
    parser.add_argument("--output", required=True)
    parser.add_argument("--network-seeds", nargs="+", type=int)
    parser.add_argument("--validation-seeds", nargs="+", type=int)
    parser.add_argument("--validation-scenarios", nargs="+")
    parser.add_argument("--eligible-updates", nargs="+", type=int)
    parser.add_argument("--expected-training-pairs", type=int)
    parser.add_argument("--minimum-uses-per-training-pair", type=int, default=1)
    args=parser.parse_args(argv)
    result = aggregate_common_update(
        args.seed_dirs, args.output,
        expected_network_seeds=args.network_seeds,
        expected_validation_seeds=args.validation_seeds,
        expected_scenarios=args.validation_scenarios,
        eligible_updates=args.eligible_updates,
        expected_training_pairs=args.expected_training_pairs,
        minimum_uses_per_training_pair=args.minimum_uses_per_training_pair,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
