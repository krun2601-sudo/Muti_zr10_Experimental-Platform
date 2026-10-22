from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import yaml

from ..config import load_config
from ..recording import jsonable
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
        "parameterized_baselines": list(manifest.get("methods", {}).get("parameterized_baselines", [])),
        "rules": list(manifest.get("rules", [])),
    }


def _read_baseline_selections(directory: str | Path, required_methods) -> dict[str, dict]:
    directory = Path(directory).resolve()
    selections = {}
    for method in required_methods:
        path = directory / method / f"selected_{method}.json"
        if not path.is_file():
            # Also support a flat folder for users who copied only the frozen JSONs.
            path = directory / f"selected_{method}.json"
        if not path.is_file():
            raise ValueError(f"missing validation-selected parameters for {method}: expected selected_{method}.json under {directory}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("method") != method or not isinstance(data.get("selected_params"), dict):
            raise ValueError(f"invalid baseline selection file: {path}")
        # Defensive leakage check: selection documents produced by our tuner record
        # all configs/seeds. Reject a document that obviously names held-out tests.
        validation_configs = " ".join(map(str, data.get("validation_configs", [])))
        if any(token in validation_configs for token in ("S10_heldout", "S11_heldout", "S9a_ood", "S9b_ood", "S7_overload")):
            raise ValueError(f"baseline selection for {method} appears to use held-out test scenarios")
        selections[method] = {"path": str(path), "params": copy.deepcopy(data["selected_params"])}
    return selections


def _resolved_scenarios(scenarios, root: Path, selections: dict[str, dict]):
    if not selections:
        return scenarios
    folder = root / "resolved_configs"; folder.mkdir(parents=True, exist_ok=True)
    result=[]
    for source in scenarios:
        cfg=load_config(source)
        baselines=cfg.policy.setdefault("research",{}).setdefault("baselines",{})
        for method, item in selections.items():
            baselines.setdefault(method,{}).update(copy.deepcopy(item["params"]))
        document=cfg.to_dict(); document.pop("source",None)
        path=folder/f"{Path(source).stem}_resolved.yaml"
        path.write_text(yaml.safe_dump(jsonable(document),allow_unicode=True,sort_keys=False),encoding="utf-8")
        result.append(path.resolve())
    return result


def run_split(manifest_path: str | Path, split: str, output: str | Path,
              methods=None, continue_on_error=True, paired=True,
              baseline_selection_dir: str | Path | None=None):
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

    tuning = manifest.get("baseline_tuning", {})
    if split in ("test_main", "test_ood"):
        if any(isinstance(row, dict) and row.get("split") == split for row in tuning.values()):
            raise ValueError("manifest illegally assigns a test split to tuning")

    parameterized = set(manifest.get("methods", {}).get("parameterized_baselines", []))
    required = sorted(parameterized.intersection(chosen))
    selections = {}
    if split in ("test_main", "test_ood") and required:
        if baseline_selection_dir is None:
            raise ValueError(
                "test split includes parameterized baselines but no frozen validation selections were supplied; "
                "run zr10lab.research.baseline_tuning first and pass --baseline-selections"
            )
        selections = _read_baseline_selections(baseline_selection_dir, required)

    root = Path(output).resolve() / split
    root.mkdir(parents=True, exist_ok=True)
    run_scenarios = _resolved_scenarios(scenarios, root, selections)
    snapshot = {
        "manifest": str(path), "split": split,
        "source_scenarios": [str(p) for p in scenarios],
        "resolved_scenarios": [str(p) for p in run_scenarios],
        "seeds": seeds, "methods": chosen,
        "baseline_selections": selections,
        "rules": manifest.get("rules", []),
    }
    (root / "protocol_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    batch_root = run_batch(run_scenarios, chosen, seeds, root,
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
    parser.add_argument("--baseline-selections",
                        help="folder containing validation-selected selected_<method>.json files")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--describe", action="store_true",
                        help="print resolved split without running any experiment")
    parser.add_argument("--no-paired", action="store_true")
    args = parser.parse_args(argv)
    if args.describe:
        print(json.dumps(describe_split(args.manifest, args.split), ensure_ascii=False, indent=2))
        return
    root = run_split(args.manifest, args.split, args.output, args.methods,
                     continue_on_error=not args.fail_fast, paired=not args.no_paired,
                     baseline_selection_dir=args.baseline_selections)
    print(root)


if __name__ == "__main__":
    main()
