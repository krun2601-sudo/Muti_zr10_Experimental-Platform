from __future__ import annotations

import json

import numpy as np
import pytest

from zr10lab.config import load_config
from zr10lab.research.candidate_feature_mappo import (
    FeatureCandidateActorCritic,
    FeatureCandidateResearchMARLEnv,
)
from zr10lab.research.candidate_mappo_dispatch import _checkpoint_implementation


def test_feature_candidate_view_has_semantic_features_and_zero_padding():
    cfg = load_config("configs/research/search_monitor_base.yaml")
    env = FeatureCandidateResearchMARLEnv(
        cfg, seed=17, max_targets=8, top_search_cells=65, max_candidates=512)
    obs, state, mask, features = env.reset(seed=17)
    assert obs.shape == (len(cfg.active_devices), env.obs_dim)
    assert state.shape == (len(cfg.active_devices) * env.obs_dim,)
    assert mask.shape == (len(cfg.active_devices), 512)
    assert features.shape == (len(cfg.active_devices), 512, env.candidate_feature_dim)
    assert np.isfinite(features).all()
    for agent in range(len(cfg.active_devices)):
        valid = int(mask[agent].sum())
        assert valid > 0
        assert features[agent, 0, 0] == pytest.approx(1.0)
        assert features[agent, 0, 1:4].sum() == pytest.approx(0.0)
        assert np.allclose(features[agent, valid:], 0.0)


def test_feature_actor_logits_are_candidate_permutation_equivariant():
    torch = pytest.importorskip("torch")
    torch.manual_seed(3)
    net = FeatureCandidateActorCritic(
        obs_dim=9, state_dim=36, candidate_feature_dim=7,
        max_candidates=6, hidden=32, device="cpu")
    obs = torch.randn(4, 9)
    features = torch.randn(4, 6, 7)
    permutation = torch.tensor([3, 0, 5, 1, 4, 2])
    with torch.no_grad():
        base = net.model.logits(obs, features)
        changed = net.model.logits(obs, features[:, permutation])
    assert torch.allclose(changed, base[:, permutation], atol=1e-6, rtol=1e-6)


def test_dispatch_reads_sidecar_implementation_without_loading_weights(tmp_path):
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"not-a-real-torch-checkpoint")
    sidecar = tmp_path / "model.pt.json"
    sidecar.write_text(json.dumps({"implementation": "candidate_feature_v2"}), encoding="utf-8")
    assert _checkpoint_implementation(checkpoint) == "candidate_feature_v2"
