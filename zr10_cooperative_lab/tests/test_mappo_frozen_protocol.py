from __future__ import annotations

from zr10lab.config import load_config
from zr10lab.research.mappo_protocol import MultiScenarioResearchEnv, _observation_capacity
from zr10lab.research.runner import _policy_builder_name


def test_mappo_uses_frozen_full_grid_observation_capacity():
    cfg = load_config("configs/research/scenarios/S1_single.yaml")
    assert _observation_capacity(cfg) == (8, 65)
    env = MultiScenarioResearchEnv([cfg], network_seed=5101, episode_seeds=[1001, 1002])
    assert env.max_targets == 8
    assert env.top_search_cells == 65
    assert env.obs_dim == 7 + 8 * 10 + 65 * 3 + 3
    obs, state = env.reset()
    assert obs.shape == (len(cfg.active_devices), env.obs_dim)
    assert state.shape == (len(cfg.active_devices) * env.obs_dim,)
    assert env.env.seed == 1001


def test_mappo_cycles_frozen_scenario_seed_product_not_network_seed():
    cfg1 = load_config("configs/research/scenarios/S1_single.yaml")
    cfg2 = load_config("configs/research/scenarios/S2_staggered.yaml")
    env = MultiScenarioResearchEnv(
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


def test_mappo_provenance_names_actual_builder():
    assert _policy_builder_name("mappo").endswith(":MAPPOPolicy")
    assert _policy_builder_name("safe_mappo").endswith(":SafeMAPPOPolicy")
    assert _policy_builder_name("ecprh").endswith(":build_paper_policy")
