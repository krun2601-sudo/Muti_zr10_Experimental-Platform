from __future__ import annotations

import pytest

from zr10lab.research.learning_statistics import aggregate_learning_replicates


def _row(scenario, env_seed, network_seed, loss, visible):
    return {
        "scenario": scenario,
        "seed": env_seed,
        "network_seed": network_seed,
        "method": "mappo",
        "research_total_loss_s": loss,
        "research_monitor_visible_ratio": visible,
    }


def test_averages_network_replicas_within_environment_case():
    rows = [
        _row("S10", 3001, 5101, 2.0, .8),
        _row("S10", 3001, 5102, 4.0, .6),
        _row("S10", 3002, 5101, 6.0, .5),
        _row("S10", 3002, 5102, 10.0, .3),
    ]
    means, variability = aggregate_learning_replicates(
        rows, expected_network_seeds=[5101, 5102])
    assert len(means) == 2  # paired sample size is environments, not 4 replicas
    first = next(row for row in means if row["seed"] == 3001)
    assert first["research_total_loss_s"] == pytest.approx(3.0)
    assert first["research_monitor_visible_ratio"] == pytest.approx(.7)
    assert first["network_replica_count"] == 2
    loss_var = next(row for row in variability
                    if row["environment_seed"] == 3001 and row["metric"] == "research_total_loss_s")
    assert loss_var["network_seed_std"] == pytest.approx(2**0.5)


def test_rejects_missing_network_replica():
    rows = [
        _row("S10", 3001, 5101, 2.0, .8),
        _row("S10", 3001, 5102, 4.0, .6),
        _row("S10", 3002, 5101, 6.0, .5),
    ]
    with pytest.raises(ValueError, match="network seeds"):
        aggregate_learning_replicates(rows, expected_network_seeds=[5101, 5102])


def test_rejects_duplicate_network_seed():
    rows = [
        _row("S10", 3001, 5101, 2.0, .8),
        _row("S10", 3001, 5101, 4.0, .6),
    ]
    with pytest.raises(ValueError, match="network seeds|duplicate"):
        aggregate_learning_replicates(rows, expected_network_seeds=[5101, 5102])
