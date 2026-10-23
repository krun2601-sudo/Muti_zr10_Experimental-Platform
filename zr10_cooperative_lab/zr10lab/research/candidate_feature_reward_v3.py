from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import candidate_feature_mappo as base
from . import candidate_feature_runtime as sparse
from .mappo import MAPPOTrainConfig, _torch


IMPLEMENTATION = "candidate_feature_v3_freshness"
TRAINING_OBJECTIVE = "freshness_recovery_v1"
FRESHNESS_RECOVERY_WEIGHT = 1.0


def freshness_recovery(before_ages, after_ages, age_cap_s: float) -> float:
    """Decision-level credit for actually refreshing stale search cells.

    Only positive per-cell age reduction is rewarded. Mere motion, repeated viewing
    of an already-fresh cell, or aging without sensing receives zero recovery.
    The quantity is derived only from policy-visible search age state.
    """
    before = np.asarray(before_ages, dtype=float)
    after = np.asarray(after_ages, dtype=float)
    if before.shape != after.shape:
        raise ValueError(f"search-age shape mismatch: {before.shape} != {after.shape}")
    cap = float(age_cap_s)
    if cap <= 0 or not np.isfinite(cap):
        raise ValueError("age_cap_s must be positive and finite")
    if before.size == 0:
        return 0.0
    decrease = np.maximum(before - after, 0.0)
    return float(np.sum(decrease) / cap)


class FreshnessFeatureCandidateResearchMARLEnv(base.FeatureCandidateResearchMARLEnv):
    """v2 candidate-feature environment plus search-freshness recovery shaping."""

    def __init__(self, *args, freshness_recovery_weight=FRESHNESS_RECOVERY_WEIGHT, **kwargs):
        super().__init__(*args, **kwargs)
        self.freshness_recovery_weight = float(freshness_recovery_weight)
        if self.freshness_recovery_weight < 0:
            raise ValueError("freshness_recovery_weight must be nonnegative")

    def step(self, indices):
        before = np.asarray(self._mission.last_search.ages_s, dtype=float).copy()
        obs, state, mask, features, reward, cost, done, info = super().step(indices)
        after = np.asarray(self._mission.last_search.ages_s, dtype=float).copy()
        age_cap = float(self.cfg.policy.get("research", {}).get("search", {}).get("age_cap_s", 120.0))
        recovery = freshness_recovery(before, after, age_cap)
        shaped = float(reward + self.freshness_recovery_weight * recovery)
        info = dict(info)
        info.update({
            "freshness_recovery": recovery,
            "freshness_recovery_weight": self.freshness_recovery_weight,
            "base_reward_before_freshness": float(reward),
            "training_objective": TRAINING_OBJECTIVE,
        })
        return obs, state, mask, features, shaped, cost, done, info


class FreshnessMultiScenarioFeatureEnv(base.MultiScenarioFeatureEnv):
    def _make_env(self, cfg_index: int, env_seed: int):
        return FreshnessFeatureCandidateResearchMARLEnv(
            self.configs[int(cfg_index)], seed=int(env_seed),
            max_targets=self.max_targets, top_search_cells=self.top_search_cells,
            max_candidates=self.max_candidates,
            freshness_recovery_weight=FRESHNESS_RECOVERY_WEIGHT,
        )


class FreshnessFeatureCandidateMAPPOPolicy(sparse.SparseFeatureCandidateMAPPOPolicy):
    """Inference wrapper for v3 checkpoints; runtime action semantics equal v2."""

    def __init__(self, cfg, *, safe=False):
        old = base.IMPLEMENTATION
        base.IMPLEMENTATION = IMPLEMENTATION
        try:
            super().__init__(cfg, safe=safe)
        finally:
            base.IMPLEMENTATION = old


class FreshnessFeatureCandidateSafeMAPPOPolicy(FreshnessFeatureCandidateMAPPOPolicy):
    def __init__(self, cfg):
        super().__init__(cfg, safe=True)


def _annotate_checkpoint(path: str | Path) -> None:
    torch, _ = _torch()
    path = Path(path)
    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    checkpoint["training_objective"] = TRAINING_OBJECTIVE
    checkpoint["freshness_recovery_weight"] = FRESHNESS_RECOVERY_WEIGHT
    torch.save(checkpoint, path)
    sidecar = Path(str(path) + ".json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    metadata["training_objective"] = TRAINING_OBJECTIVE
    metadata["freshness_recovery_weight"] = FRESHNESS_RECOVERY_WEIGHT
    sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def train_freshness_feature_mappo(train_configs, output_dir, *, safe=False, seed=0,
                                   training_env_seeds=None,
                                   settings: MAPPOTrainConfig | None=None,
                                   device="cpu", checkpoint_every=25):
    """Train sparse v2 scorer with only the search-credit signal changed."""
    old_env = base.MultiScenarioFeatureEnv
    old_actor = base.FeatureCandidateActorCritic
    old_impl = base.IMPLEMENTATION
    base.MultiScenarioFeatureEnv = FreshnessMultiScenarioFeatureEnv
    base.FeatureCandidateActorCritic = sparse.SparseFeatureCandidateActorCritic
    base.IMPLEMENTATION = IMPLEMENTATION
    try:
        checkpoints = base.train_feature_candidate_mappo(
            train_configs, output_dir, safe=safe, seed=seed,
            training_env_seeds=training_env_seeds, settings=settings,
            device=device, checkpoint_every=checkpoint_every)
    finally:
        base.MultiScenarioFeatureEnv = old_env
        base.FeatureCandidateActorCritic = old_actor
        base.IMPLEMENTATION = old_impl

    for checkpoint in checkpoints:
        _annotate_checkpoint(checkpoint)
    index_files = sorted(Path(output_dir).glob("*feature_mappo_seed*_training_index.json"))
    if len(index_files) == 1:
        index = json.loads(index_files[0].read_text(encoding="utf-8"))
        index["implementation"] = IMPLEMENTATION
        index["training_objective"] = TRAINING_OBJECTIVE
        index["freshness_recovery_weight"] = FRESHNESS_RECOVERY_WEIGHT
        index_files[0].write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return checkpoints


def select_freshness_checkpoint(checkpoints, validation_configs, seeds, output_dir,
                                *, safe=False, device="cpu"):
    old_impl = base.IMPLEMENTATION
    base.IMPLEMENTATION = IMPLEMENTATION
    try:
        chosen = base.select_feature_checkpoint(
            checkpoints, validation_configs, seeds, output_dir,
            safe=safe, device=device)
    finally:
        base.IMPLEMENTATION = old_impl
    path = Path(output_dir) / "selected_checkpoint.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["implementation"] = IMPLEMENTATION
    document["training_objective"] = TRAINING_OBJECTIVE
    document["freshness_recovery_weight"] = FRESHNESS_RECOVERY_WEIGHT
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return chosen


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Freshness-shaped feature-candidate MAPPO")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("train")
    p.add_argument("configs", nargs="+")
    p.add_argument("--output", required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--env-seeds", nargs="+", type=int)
    p.add_argument("--safe", action="store_true")
    p.add_argument("--updates", type=int, default=50)
    p.add_argument("--rollout-steps", type=int, default=128)
    p.add_argument("--checkpoint-every", type=int, default=25)
    p.add_argument("--device", default="cpu")
    p = sub.add_parser("select")
    p.add_argument("checkpoints", nargs="+")
    p.add_argument("--configs", nargs="+", required=True)
    p.add_argument("--seeds", nargs="+", type=int, required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--safe", action="store_true")
    p.add_argument("--device", default="cpu")
    args = parser.parse_args(argv)
    if args.command == "train":
        settings = MAPPOTrainConfig(updates=args.updates, rollout_steps=args.rollout_steps)
        paths = train_freshness_feature_mappo(
            args.configs, args.output, safe=args.safe, seed=args.seed,
            training_env_seeds=args.env_seeds, settings=settings,
            device=args.device, checkpoint_every=args.checkpoint_every)
        print("\n".join(map(str, paths)))
    else:
        print(json.dumps(select_freshness_checkpoint(
            args.checkpoints, args.configs, args.seeds, args.output,
            safe=args.safe, device=args.device), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
