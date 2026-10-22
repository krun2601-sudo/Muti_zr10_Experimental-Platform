from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
from typing import Any


_PACKAGES = (
    "numpy", "scipy", "PyYAML", "opencv-python", "matplotlib",
    "gymnasium", "torch", "pytest", "zr10-cooperative-lab",
)


def _package_versions() -> dict[str, str | None]:
    result = {}
    for name in _PACKAGES:
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd), check=False,
                              capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def runtime_provenance() -> dict[str, Any]:
    # Starting from the installed source location lets editable installs and normal
    # repository checkouts resolve the project root. Archive/zip installs simply
    # record null git fields instead of failing an experiment.
    source = Path(__file__).resolve()
    root_text = _git(["rev-parse", "--show-toplevel"], source.parent)
    root = Path(root_text) if root_text else source.parent
    commit = _git(["rev-parse", "HEAD"], root) if root_text else None
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], root) if root_text else None
    status = _git(["status", "--porcelain"], root) if root_text else None
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "git": {
            "commit": commit,
            "branch": branch,
            "dirty": None if status is None else bool(status),
        },
        "packages": _package_versions(),
    }


def write_research_provenance(folder: str | Path, *, cfg=None, extra: dict[str, Any] | None = None) -> Path:
    path = Path(folder) / "research_provenance.json"
    payload = runtime_provenance()
    if cfg is not None:
        payload["config_source"] = str(getattr(cfg, "source", "") or "")
        research = getattr(cfg, "policy", {}).get("research", {})
        payload["scenario_id"] = str(research.get("scenario", {}).get("id", ""))
        payload["method_config"] = str(research.get("method", ""))
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
