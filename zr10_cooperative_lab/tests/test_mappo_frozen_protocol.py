from __future__ import annotations

import numpy as np

from zr10lab.config import load_config
from zr10lab.research.candidate_mappo import (
    MultiScenarioCandidateEnv,
    _capacity,
)
from zr10lab.research.runner import _policy_builder_name


def test_mappo_uses_frozen_full_grid_and_candidate_capacity():
    cfg = load_config("configs/research/scenarios/S1_single.yaml")
    assert _capacity(cfg) == (8, 63, 512)
    env = MultiScenarioCandidateEnv([cfg], network_seed=5101, episode_seeds=[1001, 1002])
    assert env.max_targets == 8
    assert env.top_search_cells == 63
    assert env.max_candidates == 512
    assert env.obs_dim == 7 + 8 * 10 + 63 * 3 + 3
    obs, state, mask = env.reset()
    assert obs.shape == (len(cfg.active_devices), env.obs_dim)
    assert state.shape == (len(cfg.active_devices) * env.obs_dim,)
    assert mask.shape == (len(cfg.active_devices), 512)
    assert np.all(mask.sum(axis=1) >= 2)  # hold + at least one search primitive
    assert env.env.seed == 1001


def test_candidate_mask_matches_common_primitive_factory_exactly():
    cfg = load_config("configs/research/scenarios/S1_single.yaml")
    env = MultiScenarioCandidateEnv([cfg], network_seed=5101, episode_seeds=[1001])
    _, _, mask = env.reset()
    primitive_set = env.env._primitive_set
    assert primitive_set is not None
    for agent, device in enumerate(cfg.active_devices):
        rows = primitive_set.by_device[device.id]
        assert int(mask[agent].sum()) == len(rows)
        assert rows[0].kind == "hold"
        assert all(mask[agent, :len(rows)])
        assert not np.any(mask[agent, len(rows):])


def test_candidate_index_executes_the_corresponding_primitive():
    cfg = load_config("configs/research/scenarios/S1_single.yaml")
    env = MultiScenarioCandidateEnv([cfg], network_seed=5101, episode_seeds=[1001])
    _, _, mask = env.reset()
    before = env.env._candidates
    assert before is not None
    # Select the first non-hold candidate for every device. The step must be valid
    # under the same mask and report the selected primitive kinds.
    action = np.asarray([1 if row[1] else 0 for row in mask], dtype=int)
    _, _, next_mask, _, _, _, info = env.step(action)
    expected = [before[i][int(action[i])].kind for i in range(len(action))]
    assert info["selected_kinds"] == expected
    assert next_mask.shape == mask.shape


def test_mappo_cycles_frozen_scenario_seed_product_not_network_seed():
    cfg1 = load_config("configs/research/scenarios/S1_single.yaml")
    cfg2 = load_config("configs/research/scenarios/S2_staggered.yaml")
    env = MultiScenarioCandidateEnv(
        [cfg1, cfg2], network_seed=9107, episode_seeds=[1001, 1002]
    )
    env.reset()
    first = (env.env.cfg.policy["research"]["scenario"]["id"], env.env.seed)
    env.reset()
    second = (env.env.cfg.policy["research"]["scenario"]["id"], env.env.seed)
    env.reset()
    third = (env.env.cfg.policy["research"]["scenario"]["id"], env.env.seed)
    assert first[1] == 1001 and second[1] == 1001 and third[1] == 1002
    assert first[0] != second[0]
    assert third[0] == first[0]
    assert all(seed != 9107 for _, seed in (first, second, third))
    assert env.episode_usage


def test_mappo_provenance_names_versioned_candidate_dispatcher():
    expected = "zr10lab.research.candidate_mappo_dispatch:build_candidate_mappo_policy"
    assert _policy_builder_name("mappo") == expected
    assert _policy_builder_name("safe_mappo") == expected
    assert _policy_builder_name("ecprh").endswith(":build_paper_policy")
