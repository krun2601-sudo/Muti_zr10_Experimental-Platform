from __future__ import annotations

import numpy as np
import pytest

from zr10lab.research.candidate_feature_reward_v3 import (
    FRESHNESS_RECOVERY_WEIGHT,
    IMPLEMENTATION,
    TRAINING_OBJECTIVE,
    freshness_recovery,
)


def test_freshness_recovery_rewards_only_actual_age_reduction():
    before = np.asarray([10.0, 5.0, 0.0, 20.0])
    after = np.asarray([0.0, 5.5, 0.2, 12.0])
    expected = (10.0 + 8.0) / 120.0
    assert freshness_recovery(before, after, 120.0) == pytest.approx(expected)


def test_freshness_recovery_does_not_reward_aging_or_repeated_fresh_view():
    assert freshness_recovery([0.0, 5.0], [0.0, 5.5], 120.0) == 0.0
    assert freshness_recovery([0.0, 0.0], [0.0, 0.1], 120.0) == 0.0


def test_freshness_recovery_rejects_invalid_inputs():
    with pytest.raises(ValueError, match="shape mismatch"):
        freshness_recovery([1.0, 2.0], [1.0], 120.0)
    with pytest.raises(ValueError, match="positive and finite"):
        freshness_recovery([1.0], [0.0], 0.0)


def test_v3_identity_is_explicit_and_fixed():
    assert IMPLEMENTATION == "candidate_feature_v3_freshness"
    assert TRAINING_OBJECTIVE == "freshness_recovery_v1"
    assert FRESHNESS_RECOVERY_WEIGHT == 1.0
