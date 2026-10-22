from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from .batch import run_batch
from .statistics import paired_comparisons


def load_manifest(path: str | Path):
    path = Path(path).resolve()
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("unsupported or invalid research experiment manifest")
    return path, data


def _resolve_scenarios(manifest_path: Path, rows):
    root = manifest_path.parent
    result = []
    for item in rows:
        p = Path(item)
        result.append((p if p.is_absolute() else root / p).resolve())
    return result


def describe_split(manifest_path: str | Path, split: str) -> dict:
    path, manifest = load_manifest(manifest_path)
    spec = manifest.get("splits", {}).get(split)
    if not isinstance(spec, dict):
        raise ValueError(f"unknown manifest split: {split}")
    return {
        "manifest": str(path),
        "split": split,
        "scenarios": [str(p) for p in _resolve_scenarios(path, spec.get("scenarios", []))],
        "seeds": [int(x) for x in spec.get("seeds", [])],
        "primary_methods": list(manifest.get("methods", {}).get("primary", [])),
        "rules": list(manifest.get("rules", [])),
    }


def run_split(manifest_path: str | Path, split: str, output: str | Path,
              methods=None, continue_on_error=True, paired=True):
    path, manifest = load_manifest(manifest_path)
    spec = manifest.get("splits", {}).get(split)
    if not isinstance(spec, dict):
        raise ValueError(f"unknown manifest split: {split}")
    scenarios = _resolve_scenarios(path, spec.get("scenarios", []))
    seeds = [int(x) for x in spec.get("seeds", [])]
    if not scenarios or not seeds:
        raise ValueError(f"split {split!r} has no scenarios or seeds")
    chosen = list(methods or manifest.get("methods", {}).get("primary", []))
    if not chosen:
        raise ValueError("no methods selected")

    # Enforce the protocol's anti-leakage boundary at the runner, not only in docs.
    if split in ("test_main", "test_ood"):
        forbidden = set()
        tuning = manifest.get("baseline_tuning", {})
        for row in tuning.values():
            if isinstance(row, dict) and row.get("split") == split:
                forbidden.add("baseline_tuning")
        if forbidden:
            raise ValueError("manifest illegally assigns a test split to tuning")

    root = Path(output).resolve() / split
    root.mkdir(parents=True, exist_ok=True)
    (root / "protocol_snapshot.json").write_text(json.dumps({
        "manifest": str(path), "split": split,
        "scenarios": [str(p) for p in scenarios], "seeds": seeds,
        "methods": chosen, "rules": manifest.get("rules", []),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    batch_root = run_batch(scenarios, chosen, seeds, root,
                           continue_on_error=continue_on_error)
    if paired and (batch_root / "run_metrics.csv").exists():
        stats = manifest.get("statistics", {})
        paired_comparisons(
            batch_root / "run_metrics.csv",
            batch_root / "paired_comparisons.csv",
            reference=str(stats.get("reference_method", "ecprh")),
            bootstrap_samples=int(stats.get("bootstrap_samples", 10000)),
        )
    return batch_root


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run a frozen research manifest split")
    parser.add_argument("--manifest", default="configs/research/paper_experiment_manifest.yaml")
    parser.add_argument("--split", required=True,
                        choices=["train_learning_only", "validation_only", "test_main", "test_ood"])
    parser.add_argument("--methods", nargs="+")
    parser.add_argument("--output", default="runs/paper_protocol")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--describe", action="store_true",
                        help="print resolved split without running any experiment")
    parser.add_argument("--no-paired", action="store_true")
    args = parser.parse_args(argv)
    if args.describe:
        print(json.dumps(describe_split(args.manifest, args.split), ensure_ascii=False, indent=2))
        return
    root = run_split(args.manifest, args.split, args.output, args.methods,
                     continue_on_error=not args.fail_fast, paired=not args.no_paired)
    print(root)


if __name__ == "__main__":
    main()
