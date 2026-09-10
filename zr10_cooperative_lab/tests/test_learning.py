"""Gym 契约、复现性和特权真值隔离测试。"""
from dataclasses import replace

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from zr10lab.config import DeviceConfig, LabConfig
from zr10lab.learning import CooperativeObservationEnv
from zr10lab.models import Track


def learning_config():
    return LabConfig(
        devices=[DeviceConfig(str(25 + i), ip=f"192.168.144.{25+i}",
                              position_m=(0, -30 if i == 0 else 30, 0),
                              pitch_limits_deg=(-85, 80), initial_pitch_deg=15,
                              camera={"image_size": [1280, 720], "intrinsics": [
                                  {"zoom": 1, "fx": 800, "fy": 800, "cx": 640, "cy": 360}]})
                 for i in range(2)],
        system={"rate_hz": 10}, action_space={"enabled": ["pitch_deg"]},
        simulation={"seed": 1}, policy={"scan_points_m": [[120, 0, 25]]})


def assert_same(left, right):
    assert left.keys() == right.keys()
    for key in left:
        np.testing.assert_array_equal(left[key], right[key])


def test_seed_reproduces_observations_actions_and_rewards():
    env = CooperativeObservationEnv(learning_config(), max_steps=2)
    first, _ = env.reset(seed=17)
    action1 = env.action_space.sample()
    step1 = env.step(action1)
    second, _ = env.reset(seed=17)
    action2 = env.action_space.sample()
    step2 = env.step(action2)
    assert_same(first, second)
    np.testing.assert_array_equal(action1, action2)
    assert_same(step1[0], step2[0])
    assert step1[1:] == step2[1:]


def test_observation_and_masks_match_spaces_and_freeze_parameters():
    env = CooperativeObservationEnv(learning_config(), include_zoom=True, max_steps=2)
    observation, _ = env.reset(seed=0)
    assert env.observation_space.contains(observation)
    np.testing.assert_array_equal(observation["action_mask"], [0, 1, 0, 0, 1, 0])
    decoded = env.decode_action(np.ones(6))
    assert all(a.yaw_deg is None and a.zoom is None and a.pitch_deg == 80 for a in decoded.values())
    old = env.context.devices.copy()
    after, _, _, _, _ = env.step(np.ones(6))
    assert env.observation_space.contains(after)
    assert all(env.context.devices[k].yaw_deg == old[k].yaw_deg and env.context.devices[k].zoom == old[k].zoom for k in old)


def test_no_raw_truth_enters_observation_or_context():
    env = CooperativeObservationEnv(learning_config())
    original, info = env.reset(seed=3)
    # 修改私有奖励真值读取器，观测完全不受影响。光学检测来自仿真场景
    # 本身是合法的传感器输入，不能把“使用检测”误判为真值泄露。
    env._world.truth = lambda: {"SECRET_ID": (9e9, -9e9, 3e9)}
    assert_same(original, env._observation())
    assert "truth" not in vars(env.context)
    assert "truth" not in info
    assert not any("truth" in key or "target_id" in key for key in original)


def test_time_limit_is_truncation_and_requires_reset():
    env = CooperativeObservationEnv(learning_config(), max_steps=1)
    env.reset(seed=1)
    _, _, terminated, truncated, _ = env.step(np.zeros(env.action_space.shape))
    assert not terminated and truncated
    with pytest.raises(RuntimeError):
        env.step(np.zeros(env.action_space.shape))


def test_nonfinite_or_wrong_shape_actions_fail_before_advance():
    env = CooperativeObservationEnv(learning_config())
    env.reset(seed=1)
    before = env.context.t
    with pytest.raises(ValueError):
        env.step(np.full(env.action_space.shape, np.nan))
    with pytest.raises(ValueError):
        env.step(np.zeros(1))
    assert env.context.t == before


def test_gymnasium_checker():
    from gymnasium.utils.env_checker import check_env
    env = CooperativeObservationEnv(learning_config(), max_steps=4)
    check_env(env, skip_render_check=True)


def test_existing_track_keeps_slot_when_another_track_disappears():
    env = CooperativeObservationEnv(learning_config(), max_targets=3)
    env.reset(seed=1)
    def track(key, x):
        return Track(key, env.context.t, (x, 0, 20), (0, 0, 0), tuple(map(tuple, np.eye(6))),
                     env.context.t, 3, "confirmed", ("25", "26"))
    env._slots = {}
    env._context = replace(env.context, tracks=(track("a", 100), track("b", 150)))
    first = env._observation()
    assert env._slots == {"a": 0, "b": 1}
    env._context = replace(env.context, tracks=(track("b", 150), track("c", 180)))
    second = env._observation()
    assert env._slots == {"b": 1, "c": 0}
    np.testing.assert_array_equal(first["tracks"][1], second["tracks"][1])
    np.testing.assert_array_equal(second["track_mask"], [1, 1, 0])
    assert not np.any(second["tracks"][2])
