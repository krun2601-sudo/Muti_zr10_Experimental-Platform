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
from .statistics import paired_comparisons


_TEST_TOKENS = ("S10_heldout", "S11_heldout", "S9a_ood", "S9b_ood", "S7_overload")


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


def _frozen_input_dir(manifest_path: Path, manifest: dict, key: str) -> Path | None:
    value = manifest.get("frozen_inputs", {}).get(key)
    if not value:
        return None
    path = Path(value).expanduser()
    return (path if path.is_absolute() else manifest_path.parent / path).resolve()


def _require_frozen_input_dir(manifest_path: Path, manifest: dict, key: str,
                              supplied: str | Path | None, *, label: str) -> Path:
    expected = _frozen_input_dir(manifest_path, manifest, key)
    if expected is None:
        raise ValueError(
            f"paper manifest contains no frozen {label}; the held-out test split remains locked"
        )
    if supplied is None:
        raise ValueError(
            f"test split requires explicit {label} matching the frozen manifest identity: {expected}"
        )
    actual = Path(supplied).expanduser().resolve()
    if actual != expected:
        raise ValueError(
            f"caller-supplied {label} does not match frozen manifest identity: "
            f"supplied={actual}, frozen={expected}"
        )
    return expected


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
        "learning_optional": list(manifest.get("methods", {}).get("learning_optional_after_training", [])),
        "frozen_inputs": copy.deepcopy(manifest.get("frozen_inputs", {})),
        "rules": list(manifest.get("rules", [])),
    }


def _mentions_heldout(values) -> bool:
    text = " ".join(map(str, values or []))
    return any(token in text for token in _TEST_TOKENS)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_baseline_selections(directory: str | Path, required_methods,
                              expected_sha256: dict[str, str] | None = None) -> dict[str, dict]:
    directory = Path(directory).resolve()
    expected_sha256 = dict(expected_sha256 or {})
    selections = {}
    for method in required_methods:
        path = directory / method / f"selected_{method}.json"
        if not path.is_file():
            path = directory / f"selected_{method}.json"
        if not path.is_file():
            raise ValueError(f"missing validation-selected parameters for {method}: expected selected_{method}.json under {directory}")
        expected_hash = str(expected_sha256.get(method, "")).lower()
        if not expected_hash:
            raise ValueError(f"manifest contains no frozen SHA-256 identity for baseline {method}")
        actual_hash = _sha256_file(path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"frozen baseline selection hash mismatch for {method}: "
                f"expected={expected_hash}, actual={actual_hash}, path={path}"
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("method") != method or not isinstance(data.get("selected_params"), dict):
            raise ValueError(f"invalid baseline selection file: {path}")
        if _mentions_heldout(data.get("validation_configs", [])):
            raise ValueError(f"baseline selection for {method} appears to use held-out test scenarios")
        selections[method] = {
            "path": str(path), "sha256": actual_hash,
            "params": copy.deepcopy(data["selected_params"]),
        }
    return selections


def _read_learning_selections(directory: str | Path, required_methods) -> dict[str, dict]:
    """Read validation-selected MAPPO checkpoints and reject obvious test leakage."""
    directory = Path(directory).resolve()
    selections = {}
    for method in required_methods:
        candidates = [
            directory / method / "selected_checkpoint.json",
            directory / f"selected_{method}_checkpoint.json",
        ]
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            raise ValueError(
                f"missing frozen validation-selected checkpoint for {method}; expected "
                f"{method}/selected_checkpoint.json under {directory}"
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        expected_safe = method == "safe_mappo"
        if bool(data.get("safe", False)) != expected_safe:
            raise ValueError(f"learning selection {path} safe flag does not match method {method}")
        if _mentions_heldout(data.get("validation_configs", [])):
            raise ValueError(f"learning selection for {method} appears to use held-out test scenarios")
        selected = data.get("selected")
        checkpoint = selected.get("checkpoint") if isinstance(selected, dict) else None
        if not checkpoint:
            raise ValueError(f"learning selection file contains no selected checkpoint: {path}")
        checkpoint_path = Path(checkpoint).expanduser()
        if not checkpoint_path.is_absolute():
            checkpoint_path = (path.parent / checkpoint_path).resolve()
        else:
            checkpoint_path = checkpoint_path.resolve()
        if not checkpoint_path.is_file():
            raise ValueError(f"selected checkpoint does not exist: {checkpoint_path}")
        selections[method] = {
            "path": str(path), "model_path": str(checkpoint_path),
            "device": str(data.get("device", "cpu")),
        }
    return selections


def _resolved_scenarios(scenarios, root: Path, baseline_selections: dict[str, dict],
                        learning_selections: dict[str, dict]):
    if not baseline_selections and not learning_selections:
        return scenarios
    folder = root / "resolved_configs"; folder.mkdir(parents=True, exist_ok=True)
    result=[]
    for source in scenarios:
        cfg=load_config(source)
        baselines=cfg.policy.setdefault("research",{}).setdefault("baselines",{})
        for method, item in baseline_selections.items():
            baselines.setdefault(method,{}).update(copy.deepcopy(item["params"]))
        for method, item in learning_selections.items():
            baselines.setdefault(method,{}).update({
                "model_path": item["model_path"], "device": item.get("device", "cpu")})
        document=cfg.to_dict(); document.pop("source",None)
        path=folder/f"{Path(source).stem}_resolved.yaml"
        path.write_text(yaml.safe_dump(jsonable(document),allow_unicode=True,sort_keys=False),encoding="utf-8")
        result.append(path.resolve())
    return result


def run_split(manifest_path: str | Path, split: str, output: str | Path,
              methods=None, continue_on_error=True, paired=True,
              baseline_selection_dir: str | Path | None=None,
              learning_selection_dir: str | Path | None=None):
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
    required_baselines = sorted(parameterized.intersection(chosen))
    learning_methods = set(manifest.get("methods", {}).get("learning_optional_after_training", []))
    required_learning = sorted(learning_methods.intersection(chosen))
    baseline_selections = {}
    learning_selections = {}
    if split in ("test_main", "test_ood") and required_baselines:
        frozen_baseline_dir = _require_frozen_input_dir(
            path, manifest, "baseline_selection_dir", baseline_selection_dir,
            label="frozen validation selections",
        )
        baseline_hashes = manifest.get("frozen_inputs", {}).get("baseline_selection_sha256", {})
        baseline_selections = _read_baseline_selections(
            frozen_baseline_dir, required_baselines, expected_sha256=baseline_hashes)
    if split in ("test_main", "test_ood") and required_learning:
        frozen_learning_dir = _require_frozen_input_dir(
            path, manifest, "learning_selection_dir", learning_selection_dir,
            label="validation-selected checkpoints",
        )
        learning_selections = _read_learning_selections(frozen_learning_dir, required_learning)

    root = Path(output).resolve() / split
    root.mkdir(parents=True, exist_ok=True)
    run_scenarios = _resolved_scenarios(scenarios, root, baseline_selections, learning_selections)
    snapshot = {
        "manifest": str(path), "split": split,
        "source_scenarios": [str(p) for p in scenarios],
        "resolved_scenarios": [str(p) for p in run_scenarios],
        "seeds": seeds, "methods": chosen,
        "baseline_selections": baseline_selections,
        "learning_selections": learning_selections,
        "frozen_inputs": copy.deepcopy(manifest.get("frozen_inputs", {})),
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
                        help="explicit frozen baseline folder; for paper test it must exactly match manifest frozen_inputs")
    parser.add_argument("--learning-selections",
                        help="explicit frozen learning folder; for paper test it must exactly match manifest frozen_inputs")
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
                     baseline_selection_dir=args.baseline_selections,
                     learning_selection_dir=args.learning_selections)
    print(root)


if __name__ == "__main__":
    main()
