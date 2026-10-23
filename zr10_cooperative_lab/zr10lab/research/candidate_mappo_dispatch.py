from __future__ import annotations

import json
from pathlib import Path

from .candidate_mappo import CandidateMAPPOPolicy, CandidateSafeMAPPOPolicy, _mappo_options


def _checkpoint_implementation(path: str | Path, device: str = "cpu") -> str:
    checkpoint_path = Path(path).expanduser().resolve()
    sidecar = checkpoint_path.with_suffix(checkpoint_path.suffix + ".json")
    if sidecar.is_file():
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        implementation = data.get("implementation")
        if implementation:
            return str(implementation)
    from .mappo import _torch
    torch, _ = _torch()
    data = torch.load(checkpoint_path, map_location=str(device), weights_only=False)
    implementation = data.get("implementation")
    if not implementation:
        raise ValueError(f"MAPPO checkpoint has no implementation tag: {checkpoint_path}")
    return str(implementation)


def build_candidate_mappo_policy(cfg, *, safe: bool = False):
    options = _mappo_options(cfg, safe=safe)
    path = options.get("model_path")
    if not path:
        raise ValueError("MAPPO requires a frozen model_path")
    device = str(options.get("device", "cpu"))
    implementation = _checkpoint_implementation(path, device)
    if implementation == "candidate_categorical_v1":
        return CandidateSafeMAPPOPolicy(cfg) if safe else CandidateMAPPOPolicy(cfg)
    if implementation == "candidate_feature_v2":
        from .candidate_feature_runtime import (
            SparseFeatureCandidateMAPPOPolicy,
            SparseFeatureCandidateSafeMAPPOPolicy,
        )
        return (SparseFeatureCandidateSafeMAPPOPolicy(cfg) if safe
                else SparseFeatureCandidateMAPPOPolicy(cfg))
    if implementation == "candidate_feature_v3_freshness":
        from .candidate_feature_reward_v3 import (
            FreshnessFeatureCandidateMAPPOPolicy,
            FreshnessFeatureCandidateSafeMAPPOPolicy,
        )
        return (FreshnessFeatureCandidateSafeMAPPOPolicy(cfg) if safe
                else FreshnessFeatureCandidateMAPPOPolicy(cfg))
    if implementation == "candidate_feature_v4_agentwise":
        from .candidate_feature_agentppo_v4 import (
            AgentwiseFeatureCandidateMAPPOPolicy,
            AgentwiseFeatureCandidateSafeMAPPOPolicy,
        )
        return (AgentwiseFeatureCandidateSafeMAPPOPolicy(cfg) if safe
                else AgentwiseFeatureCandidateMAPPOPolicy(cfg))
    raise ValueError(f"unsupported MAPPO checkpoint implementation: {implementation}")
