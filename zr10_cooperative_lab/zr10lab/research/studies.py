from __future__ import annotations

import argparse
import copy
import csv
import json
from pathlib import Path
from typing import Any

import yaml

from ..config import config_from_dict, load_config
from .batch import aggregate, _write_table
from .runner import run_research_simulation


def _deep_merge(target: dict, update: dict) -> dict:
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
    return target


def _explicit_yaml_override(path: str | Path) -> dict:
    """Read only fields explicitly written in an override YAML.

    Ablation files themselves extend the base for standalone use, but when applying
    one to a scenario we must not let the inherited default S2 scenario overwrite
    the scenario under test. Therefore the study runner ignores the `extends` key
    and merges only explicit fields from the ablation document.
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"override must be a YAML mapping: {path}")
    data = copy.deepcopy(data)
    data.pop("extends", None)
    return data


def apply_override(cfg, override: dict):
    raw = cfg.to_dict(); raw.pop("source", None)
    merged = _deep_merge(raw, override)
    local = config_from_dict(merged)
    local.source = cfg.source
    return local


def _set_path(mapping: dict, dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    current = mapping
    for key in keys[:-1]:
        current = current.setdefault(key, {})
        if not isinstance(current, dict):
            raise ValueError(f"cannot set {dotted}: {key} is not a mapping")
    current[keys[-1]] = value


def _run_variants(scenarios, variants, seeds, output, method="ecprh"):
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=True)
    rows = []
    for scenario_path in scenarios:
        scenario_path = Path(scenario_path).resolve()
        base = load_config(scenario_path)
        scenario_id = str(base.policy.get("research", {}).get("scenario", {}).get("id", scenario_path.stem))
        for variant_id, variant_cfg in variants:
            for seed in seeds:
                row = {"scenario": scenario_id, "method": f"{method}[{variant_id}]",
                       "variant": variant_id, "seed": int(seed), "config": str(scenario_path),
                       "status": "running", "run_dir": ""}
                rows.append(row); _write_table(root / "index.csv", rows)
                try:
                    run_dir = run_research_simulation(variant_cfg(base), method, root / "runs", int(seed))
                    row["run_dir"] = str(Path(run_dir).resolve())
                    row["status"] = "completed"
                except Exception as exc:
                    row["status"] = "failed"
                    row["error"] = f"{type(exc).__name__}: {exc}"
                _write_table(root / "index.csv", rows)
    aggregate(rows, root)
    return root


def run_ablations(scenarios, ablation_files, seeds, output="runs/ablations", include_full=True):
    variants = []
    if include_full:
        variants.append(("full", lambda cfg: copy.deepcopy(cfg)))
    for path in ablation_files:
        path = Path(path).resolve()
        override = _explicit_yaml_override(path)
        variants.append((path.stem, lambda cfg, o=override: apply_override(cfg, o)))
    return _run_variants(scenarios, variants, seeds, output, method="ecprh")


def run_sensitivity(scenarios, dotted_path: str, values, seeds,
                    output="runs/sensitivity"):
    variants = []
    for value in values:
        def transform(cfg, v=value):
            local = copy.deepcopy(cfg)
            raw = local.to_dict(); raw.pop("source", None)
            _set_path(raw, dotted_path, v)
            result = config_from_dict(raw); result.source = cfg.source
            return result
        label = f"{dotted_path}={value}"
        variants.append((label, transform))
    return _run_variants(scenarios, variants, seeds, output, method="ecprh")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run isolated ECP-RH ablation or sensitivity studies")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ablation")
    p.add_argument("--scenarios", nargs="+", required=True)
    p.add_argument("--ablations", nargs="+", required=True)
    p.add_argument("--seeds", nargs="+", type=int, required=True)
    p.add_argument("--output", default="runs/ablations")
    p = sub.add_parser("sensitivity")
    p.add_argument("--scenarios", nargs="+", required=True)
    p.add_argument("--path", required=True,
                   help="e.g. policy.research.planning.visibility_risk")
    p.add_argument("--values", nargs="+", required=True,
                   help="JSON scalars, e.g. 0.01 0.05 0.1 or '[1,2]'")
    p.add_argument("--seeds", nargs="+", type=int, required=True)
    p.add_argument("--output", default="runs/sensitivity")
    args = parser.parse_args(argv)
    if args.command == "ablation":
        root = run_ablations(args.scenarios, args.ablations, args.seeds, args.output)
    else:
        values = [json.loads(value) for value in args.values]
        root = run_sensitivity(args.scenarios, args.path, values, args.seeds, args.output)
    print(root)


if __name__ == "__main__":
    main()
