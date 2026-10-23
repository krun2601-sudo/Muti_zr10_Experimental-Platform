from __future__ import annotations

import numpy as np

from zr10lab.research.candidate_feature_agentppo_v4 import (
    ACTOR_UPDATE,
    IMPLEMENTATION,
    numpy_clipped_surrogate,
)


def test_agentwise_surrogate_clips_each_agent_before_averaging():
    ratio = np.asarray([[1.10, 1.50, 0.70, 0.95]])
    advantage = np.asarray([[2.0]])
    values = numpy_clipped_surrogate(ratio, advantage, 0.2)
    # Positive advantage: high ratios clip at 1.2, low ratios are left unchanged.
    expected = np.asarray([[2.20, 2.40, 1.40, 1.90]])
    assert np.allclose(values, expected)


def test_agentwise_update_is_not_joint_product_clipping():
    ratio = np.asarray([[1.10, 1.10, 1.10, 1.10]])
    advantage = np.asarray([[1.0]])
    agentwise = numpy_clipped_surrogate(ratio, advantage, 0.2).mean()
    joint_ratio = float(np.prod(ratio))
    joint_clipped = min(joint_ratio, 1.2)
    assert np.isclose(agentwise, 1.10)
    assert np.isclose(joint_clipped, 1.20)
    assert not np.isclose(agentwise, joint_clipped)


def test_negative_advantage_uses_standard_ppo_minimum():
    ratio = np.asarray([[0.60, 0.90, 1.10, 1.50]])
    advantage = np.asarray([[-1.0]])
    values = numpy_clipped_surrogate(ratio, advantage, 0.2)
    expected = np.minimum(ratio * advantage, np.clip(ratio, 0.8, 1.2) * advantage)
    assert np.allclose(values, expected)


def test_v4_identity_is_explicit():
    assert IMPLEMENTATION == "candidate_feature_v4_agentwise"
    assert ACTOR_UPDATE == "per_agent_clipped_ratio_v1"
