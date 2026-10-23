from __future__ import annotations

import types
from pathlib import Path

import numpy as np

from . import candidate_feature_mappo as base
from .candidate_mappo import _mappo_options
from .mappo import MAPPOTrainConfig, _torch


class SparseFeatureCandidateActorCritic(base.FeatureCandidateActorCritic):
    """Feature-scored actor that evaluates only mask-valid primitive rows.

    Padding candidates are never legal actions. Skipping their candidate-encoder
    forward passes is therefore numerically equivalent on every valid logit while
    reducing training/inference cost from max_candidates to the actual primitive
    count. The parameterization and checkpoint state_dict are unchanged.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        outer = self

        def sparse_distribution(model, obs, candidate_features, mask):
            logits = outer.masked_logits(obs, candidate_features, mask)
            return outer.torch.distributions.Categorical(logits=logits)

        self.model.distribution = types.MethodType(sparse_distribution, self.model)

    def masked_logits(self, obs, candidate_features, mask):
        torch = self.torch
        mask = mask.to(dtype=torch.bool)
        if candidate_features.shape[:-1] != mask.shape:
            raise ValueError(
                f"candidate feature/mask shape mismatch: {candidate_features.shape} vs {mask.shape}")
        if obs.shape[:-1] != mask.shape[:-1]:
            raise ValueError(f"observation/mask leading shape mismatch: {obs.shape} vs {mask.shape}")
        candidate_count = int(mask.shape[-1])
        obs_embedding = self.model.obs_encoder(obs)
        hidden = int(obs_embedding.shape[-1])
        flat_obs = obs_embedding.reshape(-1, hidden)
        flat_features = candidate_features.reshape(-1, candidate_count, candidate_features.shape[-1])
        flat_mask = mask.reshape(-1, candidate_count)
        if not bool(torch.all(flat_mask.any(dim=-1))):
            raise ValueError("every agent row must have at least one valid candidate")
        indices = flat_mask.nonzero(as_tuple=False)
        row_index = indices[:, 0]
        candidate_index = indices[:, 1]
        selected_features = flat_features[row_index, candidate_index]
        candidate_embedding = self.model.candidate_encoder(selected_features)
        selected_logits = self.model.score(
            torch.tanh(flat_obs[row_index] + candidate_embedding)
        ).squeeze(-1)
        invalid = torch.finfo(selected_logits.dtype).min
        flat_logits = torch.full(
            flat_mask.shape, invalid, dtype=selected_logits.dtype,
            device=selected_logits.device)
        flat_logits = flat_logits.index_put(
            (row_index, candidate_index), selected_logits, accumulate=False)
        return flat_logits.reshape(mask.shape)

    def deterministic(self, obs, mask, candidate_features):
        torch = self.torch
        with torch.no_grad():
            obs_t = torch.as_tensor(obs, dtype=torch.float32, device=self.device)
            mask_t = torch.as_tensor(mask, dtype=torch.bool, device=self.device)
            feat_t = torch.as_tensor(candidate_features, dtype=torch.float32, device=self.device)
            return torch.argmax(
                self.masked_logits(obs_t, feat_t, mask_t), dim=-1
            ).cpu().numpy()


class SparseFeatureCandidateMAPPOPolicy(base.FeatureCandidateMAPPOPolicy):
    """Inference-compatible v2 policy using sparse valid-candidate scoring."""

    def __init__(self, cfg, *, safe=False):
        super().__init__(cfg, safe=safe)
        state = self.net.state_dict()
        device = str(self.net.device)
        replacement = SparseFeatureCandidateActorCritic(
            self.encoder.obs_dim,
            len(cfg.active_devices) * self.encoder.obs_dim,
            self.feature_encoder.feature_dim,
            max_candidates=self.max_candidates,
            safe=safe,
            device=device,
        )
        replacement.load_state_dict(state)
        self.net = replacement


class SparseFeatureCandidateSafeMAPPOPolicy(SparseFeatureCandidateMAPPOPolicy):
    def __init__(self, cfg):
        super().__init__(cfg, safe=True)


def train_sparse_feature_candidate_mappo(*args, **kwargs):
    """Run the frozen v2 training loop with sparse-but-equivalent actor scoring."""
    original = base.FeatureCandidateActorCritic
    base.FeatureCandidateActorCritic = SparseFeatureCandidateActorCritic
    try:
        return base.train_feature_candidate_mappo(*args, **kwargs)
    finally:
        base.FeatureCandidateActorCritic = original


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Sparse runtime for feature-scored candidate MAPPO")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("train")
    p.add_argument("configs", nargs="+")
    p.add_argument("--output", required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--env-seeds", nargs="+", type=int)
    p.add_argument("--safe", action="store_true")
    p.add_argument("--updates", type=int, default=300)
    p.add_argument("--rollout-steps", type=int, default=128)
    p.add_argument("--checkpoint-every", type=int, default=25)
    p.add_argument("--device", default="cpu")
    args = parser.parse_args(argv)
    if args.command == "train":
        settings = MAPPOTrainConfig(updates=args.updates, rollout_steps=args.rollout_steps)
        checkpoints = train_sparse_feature_candidate_mappo(
            args.configs, args.output, safe=args.safe, seed=args.seed,
            training_env_seeds=args.env_seeds, settings=settings,
            device=args.device, checkpoint_every=args.checkpoint_every)
        print("\n".join(map(str, checkpoints)))


if __name__ == "__main__":
    main()
