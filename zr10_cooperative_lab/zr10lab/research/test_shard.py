from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import yaml

from ..config import load_config
from ..recording import jsonable
from .batch import run_batch
from .protocol import load_manifest, _read_baseline_selections, _resolve_scenarios


ALLOWED_SPLITS = {"test_main", "test_ood"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run_test_shard(manifest_path: str | Path, split: str, method: str,
                   scenario_index: int, output: str | Path,
                   baseline_selection_dir: str | Path | None = None):
    if split not in ALLOWED_SPLITS:
        raise ValueError(f"test shard may only run {sorted(ALLOWED_SPLITS)}, got {split!r}")

    manifest_path, manifest = load_manifest(manifest_path)
    spec = manifest.get("splits", {}).get(split)
    if not isinstance(spec, dict):
        raise ValueError(f"unknown split {split!r}")

    scenarios = _resolve_scenarios(manifest_path, spec.get("scenarios", []))
    seeds = [int(x) for x in spec.get("seeds", [])]
    if not scenarios or not seeds:
        raise ValueError(f"split {split!r} is empty")
    if scenario_index < 0 or scenario_index >= len(scenarios):
        raise IndexError(f"scenario index {scenario_index} outside 0..{len(scenarios)-1}")

    primary = set(manifest.get("methods", {}).get("primary", []))
    if method not in primary:
        raise ValueError(f"method {method!r} is not a frozen primary method")
    learning = set(manifest.get("methods", {}).get("learning_optional_after_training", []))
    if method in learning:
        raise ValueError("learning methods use the separate checkpoint-selected protocol")

    parameterized = set(manifest.get("methods", {}).get("parameterized_baselines", []))
    selections = {}
    if method in parameterized:
        if baseline_selection_dir is None:
            raise ValueError(f"{method} requires frozen validation-selected parameters")
        selections = _read_baseline_selections(baseline_selection_dir, [method])

    source = scenarios[scenario_index]
    cfg = load_config(source)
    selection_record = None
    if method in selections:
        baselines = cfg.policy.setdefault("research", {}).setdefault("baselines", {})
        baselines.setdefault(method, {}).update(copy.deepcopy(selections[method]["params"]))
        selection_path = Path(selections[method]["path"]).resolve()
        selection_record = {
            "path": str(selection_path),
            "sha256": _sha256(selection_path),
            "params": copy.deepcopy(selections[method]["params"]),
        }

    root = Path(output).resolve() / split / method / source.stem
    root.mkdir(parents=True, exist_ok=True)
    resolved = root / "resolved_config.yaml"
    document = cfg.to_dict(); document.pop("source", None)
    resolved.write_text(
        yaml.safe_dump(jsonable(document), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    snapshot = {
        "manifest": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "split": split,
        "method": method,
        "scenario_index": int(scenario_index),
        "source_scenario": str(source),
        "resolved_scenario": str(resolved),
        "seeds": seeds,
        "baseline_selection": selection_record,
        "rules": manifest.get("rules", []),
    }
    (root / "shard_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return run_batch([resolved], [method], seeds, root / "batch", continue_on_error=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run one frozen held-out test scenario-method shard")
    parser.add_argument("--manifest", default="configs/research/paper_experiment_manifest.yaml")
    parser.add_argument("--split", required=True, choices=sorted(ALLOWED_SPLITS))
    parser.add_argument("--method", required=True)
    parser.add_argument("--scenario-index", required=True, type=int)
    parser.add_argument("--output", default="runs/frozen_test")
    parser.add_argument("--baseline-selections")
    args = parser.parse_args(argv)
    print(run_test_shard(
        args.manifest, args.split, args.method, args.scenario_index, args.output,
        baseline_selection_dir=args.baseline_selections,
    ))


if __name__ == "__main__":
    main()
