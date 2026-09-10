"""决策语义测试：共视场、双站约束、冻结参数以及单站假设隔离。"""
from dataclasses import replace

import numpy as np
import pytest

from zr10lab.config import DeviceConfig, LabConfig
from zr10lab.geometry import project_world_point
from zr10lab.models import PolicyContext, Ray, Telemetry, Track
from zr10lab.policies import CooperativePolicy, build_policy


def policy_config(n=2, mode="multi", enabled=None):
    devices = [DeviceConfig(str(25 + i), ip=f"192.168.144.{25+i}",
                            position_m=(0 if i < 2 else 15, -30 if i % 2 == 0 else 30, 0),
                            pitch_limits_deg=(-85, 80),
                            camera={"image_size": [1280, 720], "intrinsics": [
                                {"zoom": 1, "fx": 800, "fy": 800, "cx": 640, "cy": 360,
                                 "distortion": [0, 0, 0, 0, 0]}]}) for i in range(n)]
    return LabConfig(devices, policy={"name": "cooperative", "mode": mode,
                                      "scan_points_m": [[120, 0, 25]], "prediction_horizon_s": 0},
                     action_space={"enabled": ["yaw_deg", "pitch_deg"] if enabled is None else enabled})


def make_track(key, point):
    return Track(key, 0.0, point, (0, 0, 0), tuple(map(tuple, np.eye(6))), 0.0, 3,
                 "confirmed", ("25", "26"))


def make_context(cfg, tracks=(), rays=(), t=0.0):
    return PolicyContext(t, .1, 0, {d.id: Telemetry(d.id, t, 0, 15) for d in cfg.devices},
                         tracks=tuple(tracks), rays=tuple(rays))


def test_multi_targets_share_two_views_without_centering_each():
    cfg = policy_config()
    tracks = (make_track("a", (120, -4, 25)), make_track("b", (120, 4, 25)))
    context = make_context(cfg, tracks)
    decision = CooperativePolicy(cfg).decide(context)
    assert len(decision.diagnostics["assignments"]) == 1
    assert all(action.target_ids == ("a", "b") for action in decision.actions.values())
    for device in cfg.devices:
        action = decision.actions[device.id]
        state = replace(context.devices[device.id], yaw_deg=action.yaw_deg, pitch_deg=action.pitch_deg)
        pixels = [project_world_point(track.position, state, device) for track in tracks]
        assert all(p is not None and 0 < p[0] < 1280 and 0 < p[1] < 720 for p in pixels)
        assert all(abs(p[0] - 640) > 5 for p in pixels)


def test_center_mode_assigns_one_target_to_at_least_two_devices():
    cfg = policy_config(mode="center")
    decision = CooperativePolicy(cfg).decide(make_context(cfg, [make_track("a", (120, 0, 25))]))
    assert sum(a.target_ids == ("a",) for a in decision.actions.values()) == 2
    assert all(len(a.target_ids) <= 1 for a in decision.actions.values())


def test_one_connected_device_cannot_claim_localization_assignment():
    cfg = policy_config()
    context = make_context(cfg, [make_track("a", (120, 0, 25))])
    context.devices["26"] = replace(context.devices["26"], connected=False)
    decision = CooperativePolicy(cfg).decide(context)
    assert not any(a.target_ids for a in decision.actions.values())
    assert decision.diagnostics["covered_track_ids"] == []


def test_frozen_parameters_never_emitted_and_center_constraint_respected():
    cfg = policy_config(mode="center", enabled=["pitch_deg"])
    decision = CooperativePolicy(cfg).decide(make_context(cfg, [make_track("a", (120, 0, 25))]))
    assert all(a.yaw_deg is None and a.zoom is None and a.parameters == {} for a in decision.actions.values())
    # 两站当前 yaw=0 不能中心跟踪位于 y=0 的目标；禁止把边缘可见当作居中。
    assert not any(a.target_ids for a in decision.actions.values())


def test_scan_pairs_aim_at_same_world_point_and_ignore_simulation_truth():
    cfg = policy_config(4)
    first = CooperativePolicy(cfg).decide(make_context(cfg))
    cfg.simulation["targets"] = [{"id": "hidden", "position": [5000, 5000, 5000]}]
    second = CooperativePolicy(cfg).decide(make_context(cfg))
    assert first == second
    for device in cfg.devices:
        action = first.actions[device.id]
        state = Telemetry(device.id, 0, action.yaw_deg, action.pitch_deg)
        assert np.allclose(project_world_point((120, 0, 25), state, device), (640, 360), atol=1e-6)


def test_single_station_search_is_explicitly_not_localization():
    cfg = policy_config()
    point = np.array([120, 0, 25], dtype=float)
    origin = np.asarray(cfg.devices[0].position_m)
    direction = point - origin
    direction /= np.linalg.norm(direction)
    ray = Ray("25", "25:0:det0", 0, tuple(origin), tuple(direction))
    context = make_context(cfg, rays=[ray])
    decision = CooperativePolicy(cfg).decide(context)
    assert decision.diagnostics["search_hypotheses"]
    assert decision.diagnostics["search_hypotheses"][0]["is_localization"] is False
    assert all(a.reason == "search_hypothesis" and not a.target_ids for a in decision.actions.values())
    assert context.tracks == ()


def test_colocated_stations_do_not_claim_geometrically_valid_tracking():
    cfg = policy_config()
    cfg.devices[1].position_m = cfg.devices[0].position_m
    decision = CooperativePolicy(cfg).decide(make_context(cfg, [make_track("a", (120, 0, 25))]))
    assert decision.diagnostics["covered_track_ids"] == []


def test_policy_factory_and_reset():
    cfg = policy_config()
    for name in ("hold", "scan", "cooperative"):
        cfg.policy["name"] = name
        policy = build_policy(cfg)
        policy.reset()
        assert set(policy.decide(make_context(cfg)).actions) == {"25", "26"}
    cfg.policy["name"] = "invalid"
    with pytest.raises(ValueError):
        build_policy(cfg)


def test_stale_telemetry_cannot_complete_a_pair():
    cfg = policy_config()
    context = make_context(cfg, [make_track("a", (120, 0, 25))], t=1.0)
    context.devices["26"] = replace(context.devices["26"], t=0.0)
    decision = CooperativePolicy(cfg).decide(context)
    assert decision.actions["26"].reason == "unavailable"
    assert not any(a.target_ids for a in decision.actions.values())


def test_blind_start_scans_discovers_and_forms_multistation_tracks():
    from zr10lab.config import load_config
    from zr10lab.fusion import FusionEngine
    from zr10lab.geometry import pixel_to_world_ray
    from zr10lab.simulation import SimulationWorld
    cfg = load_config("configs/four_zr10.yaml")
    for device in cfg.active_devices:
        device.initial_yaw_deg = -80
    world = SimulationWorld(cfg)
    fusion = FusionEngine(cfg.fusion)
    policy = CooperativePolicy(cfg)
    configs = {device.id: device for device in cfg.active_devices}
    measured = []
    for step in range(50):
        states = world.states()
        detections = world.observe()
        if step == 0:
            assert not detections  # 首帧不可见，必须真正通过动作发现目标。
        rays = [pixel_to_world_ray(d, states[d.device_id], configs[d.device_id]) for d in detections]
        tracks, _, _ = fusion.update(rays, world.t)
        context = PolicyContext(world.t, .1, step, states, tuple(detections), tuple(rays), tuple(tracks))
        decision = policy.decide(context)
        measured.append(sum(tr.measured and len(set(tr.device_ids)) >= 2 for tr in tracks))
        world.advance(decision.actions, .1)
    assert max(measured) == 2
    assert np.mean(measured[-10:]) >= 1.8
