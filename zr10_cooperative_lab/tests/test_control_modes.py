"""模式插件契约及单站居中闭环：验证物理结果，不读取模拟真值。"""
import importlib
import sys
from dataclasses import replace

import numpy as np
import pytest

from zr10lab.config import DeviceConfig, LabConfig
from zr10lab.control_modes import ImageCenterTrackPolicy, create_mode_policy, mode_catalog
from zr10lab.geometry import camera_rotation, pixel_to_world_ray, project_world_point
from zr10lab.models import Detection, PolicyContext, Telemetry, Track
from zr10lab.policies import CooperativePolicy, HoldPolicy, ScanPolicy


def config():
    d = DeviceConfig("25", position_m=(3, -4, 2), mount_rpy_deg=(12, -8, 25),
        yaw_limits_deg=(-150, 150), pitch_limits_deg=(-80, 80), calibration_verified=True,
        camera={"image_size": [1280, 720], "intrinsics": [
            dict(zoom=1, fx=850, fy=800, cx=610, cy=345, dist=[-.05, .003, .001, -.001, 0]),
            dict(zoom=10, fx=8500, fy=8000, cx=610, cy=345, dist=[0] * 5)]})
    cfg = LabConfig([d], policy={"scan_points_m": [[120, 0, 30]]}, action_space={"enabled": ["yaw_deg", "pitch_deg"]})
    cfg.control_center = {}
    return cfg


def detection(cfg, state, xyz, confidence=.9, local_id="0", frame=1):
    u, v = project_world_point(xyz, state, cfg.devices[0])
    return Detection("25", frame, state.t, (u - 5, v - 5, u + 5, v + 5), confidence,
                     local_id=local_id, image_size=(1280, 720))


def context(state, detections=(), rays=(), tracks=(), t=None):
    return PolicyContext(state.t if t is None else t, .1, 0, {"25": state}, tuple(detections), tuple(rays), tuple(tracks))


def test_catalog_factory_and_config_isolation():
    cfg = config()
    catalog = {row["id"]: row for row in mode_catalog(cfg)}
    assert set(catalog) == {"manual", "hold", "localize", "scan", "track", "center", "multi"}
    assert not catalog["manual"]["requires_detection"] and catalog["track"]["requires_detection"]
    # 新会话可重载模块，不能以测试收集时缓存的旧Python类身份判断新实例。
    assert type(create_mode_policy(cfg, "scan")).__name__ == "ScanPolicy"
    assert type(create_mode_policy(cfg, "manual")).__name__ == "HoldPolicy"
    assert type(create_mode_policy(cfg, "localize")).__name__ == "HoldPolicy"
    assert catalog["localize"]["requires_detection"] and catalog["localize"]["requires_calibration"]
    assert type(create_mode_policy(cfg, "track")).__name__ == "ImageCenterTrackPolicy"
    for mode in ("center", "multi"):
        policy = create_mode_policy(cfg, mode)
        assert type(policy).__name__ == "CooperativePolicy" and policy.cfg.policy["mode"] == mode
    assert "mode" not in cfg.policy and "control_mode" not in cfg.policy
    with pytest.raises(ValueError, match="未知控制模式"):
        create_mode_policy(cfg, "typo")


@pytest.mark.parametrize("row", [
    {"id": "oops"}, {"id": "bad space", "policy": "x:Y"},
    {"id": "track", "settings": []}, {"id": "track", "requires_detection": "false"},
    {"id": "track", "policy": "bad"}, {"id": "track", "polcy": "x:Y"},
])
def test_registry_rejects_misconfigured_modes(row):
    cfg = config()
    cfg.control_center = {"modes": [row]}
    with pytest.raises(ValueError):
        mode_catalog(cfg)
    cfg.control_center = {"modes": [{"id": "track"}, {"id": "track"}]}
    with pytest.raises(ValueError, match="重复"):
        mode_catalog(cfg)


def test_plugin_entry_reload_override_and_settings(tmp_path, monkeypatch):
    module = tmp_path / "zr10mode_plugin_example.py"
    module.write_text("from zr10lab.policies import HoldPolicy\nclass Demo(HoldPolicy):\n    version = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    cfg = config()
    cfg.control_center = {"modes": [{"id": "research", "label": "实验算法", "policy": "zr10mode_plugin_example:Demo", "settings": {"nested": {"a": 2}}}]}
    try:
        first = create_mode_policy(cfg, "research")
        assert first.version == 1 and first.cfg.policy["nested"]["a"] == 2
        assert "nested" not in cfg.policy
        # 同一秒、同文件大小的修改也必须立刻生效，不能静默复用旧 pyc。
        module.write_text("from zr10lab.policies import HoldPolicy\nclass Demo(HoldPolicy):\n    version = 2\n", encoding="utf-8")
        assert create_mode_policy(cfg, "research", reload=True).version == 2
        cfg.control_center["modes"][0]["id"] = "scan"
        assert create_mode_policy(cfg, "scan").version == 2
        module.write_text("class Demo:\n    def __init__(self, cfg): pass\n", encoding="utf-8")
        with pytest.raises(TypeError, match="reset"):
            create_mode_policy(cfg, "scan", reload=True)
    finally:
        sys.modules.pop("zr10mode_plugin_example", None)
        importlib.invalidate_caches()


@pytest.mark.parametrize("alias", ["custom", "class_path", "entrypoint", "name", "type"])
def test_legacy_custom_policy_configuration_preserves_algorithm(alias, tmp_path, monkeypatch):
    module = tmp_path / "zr10legacy_custom_test.py"
    module.write_text("from zr10lab.policies import HoldPolicy\nclass Demo(HoldPolicy):\n    pass\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    cfg = config()
    original = {"name": "custom", "research_parameter": {"gain": 7}}
    if alias == "name":
        original["name"] = "zr10legacy_custom_test:Demo"
    elif alias == "type":
        original.pop("name")
        original.update(type="custom", custom="zr10legacy_custom_test:Demo")
    else:
        original[alias] = "zr10legacy_custom_test:Demo"
    cfg.policy = original.copy()
    try:
        catalog = {entry["id"]: entry for entry in mode_catalog(cfg)}
        assert catalog["custom"]["policy"] == "zr10legacy_custom_test:Demo"
        assert catalog["custom"]["requires_detection"] and catalog["custom"]["requires_calibration"]
        policy = create_mode_policy(cfg, "custom", reload=True)
        assert type(policy).__name__ == "Demo"
        assert all(policy.cfg.policy[key] == value for key, value in original.items())
        assert cfg.policy == original
    finally:
        sys.modules.pop("zr10legacy_custom_test", None)


def test_explicit_custom_mode_can_override_legacy_registration():
    cfg = config()
    cfg.policy.update(name="custom", custom="old_package:OldPolicy")
    cfg.control_center = {"modes": [{"id": "custom", "policy": "new_package:NewPolicy", "requires_detection": False}]}
    custom = next(entry for entry in mode_catalog(cfg) if entry["id"] == "custom")
    assert custom["policy"] == "new_package:NewPolicy" and not custom["requires_detection"]


def test_legacy_custom_missing_or_invalid_entry_fails_explicitly():
    cfg = config()
    cfg.policy["name"] = "custom"
    with pytest.raises(ValueError, match="旧custom"):
        mode_catalog(cfg)
    cfg.policy["custom"] = "bad import"
    with pytest.raises(ValueError, match="module:Class"):
        mode_catalog(cfg)


def test_one_camera_centers_off_axis_target_with_mount_and_roll():
    cfg = config()
    state = Telemetry("25", 2., 27, 16, roll_deg=23)
    point = np.asarray(cfg.devices[0].position_m) + camera_rotation(state, cfg.devices[0]) @ [120, -25, 15]
    det = detection(cfg, state, point)
    decision = create_mode_policy(cfg, "track").decide(context(state, [det]))
    action = decision.actions["25"]
    assert action.reason == "image_center_track" and action.target_ids == (det.key,)
    future = replace(state, yaw_deg=action.yaw_deg, pitch_deg=action.pitch_deg)
    np.testing.assert_allclose(project_world_point(point, future, cfg.devices[0]), [610, 345], atol=2e-5)
    assert not decision.diagnostics["targets"]["25"]["is_localization"]
    assert action.ttl_s == .5 and action.issued_t == state.t


def test_exposure_aligned_ray_prevents_using_current_pose_for_old_frame():
    cfg = config()
    exposure = Telemetry("25", 1., 10, 15, roll_deg=13)
    point = np.asarray(cfg.devices[0].position_m) + camera_rotation(exposure, cfg.devices[0]) @ [100, -10, 5]
    det = detection(cfg, exposure, point)
    ray = pixel_to_world_ray(det, exposure, cfg.devices[0])
    latest = replace(exposure, t=1.3, yaw_deg=24)
    policy = create_mode_policy(cfg, "track")
    rejected = policy.decide(context(latest, [det]))
    assert rejected.actions["25"].yaw_deg is None
    action = policy.decide(context(latest, [det], [ray])).actions["25"]
    aimed = replace(latest, yaw_deg=action.yaw_deg, pitch_deg=action.pitch_deg)
    np.testing.assert_allclose(project_world_point(point, aimed, cfg.devices[0]), [610, 345], atol=2e-5)


def test_identity_continuity_survives_detector_local_id_changes():
    cfg = config()
    state = Telemetry("25", 1., 0, 15)
    d = cfg.devices[0]
    chosen = np.asarray(d.position_m) + camera_rotation(state, d) @ [100, -8, 0]
    other = np.asarray(d.position_m) + camera_rotation(state, d) @ [100, 22, 0]
    policy = create_mode_policy(cfg, "track")
    first = policy.decide(context(state, [detection(cfg, state, chosen, .95, "0"), detection(cfg, state, other, .5, "1")]))
    a = first.actions["25"]
    moved = replace(state, t=1.1, yaw_deg=a.yaw_deg, pitch_deg=a.pitch_deg)
    keep = detection(cfg, moved, chosen, .5, "1", 2)
    distractor = detection(cfg, moved, other, .99, "0", 2)
    second = policy.decide(context(moved, [distractor, keep]))
    assert second.actions["25"].target_ids == (keep.key,)
    # 目标消失而另一个目标仍在时，记忆窗口内停止，不立即追错目标。
    lost = policy.decide(context(moved, [distractor], t=1.2))
    assert lost.actions["25"].yaw_deg is None
    assert lost.diagnostics["rejections"]["25"] == "target_lost_hold"


def test_masks_limits_offline_and_unknown_zoom_emit_no_unsafe_motion():
    cfg = config()
    state = Telemetry("25", 1., 0, 15)
    point = np.asarray(cfg.devices[0].position_m) + camera_rotation(state, cfg.devices[0]) @ [100, -10, 10]
    det = detection(cfg, state, point)
    cfg.action_space["enabled"] = ["pitch_deg"]
    action = create_mode_policy(cfg, "track").decide(context(state, [det])).actions["25"]
    assert action.yaw_deg is None and action.pitch_deg is not None and action.zoom is None
    cfg.action_space["enabled"] = ["yaw_deg", "pitch_deg"]
    cfg.devices[0].yaw_limits_deg = (-1, 1)
    assert create_mode_policy(cfg, "track").decide(context(state, [det])).actions["25"].yaw_deg is None
    cfg.devices[0].yaw_limits_deg = (-150, 150)
    for bad in (replace(state, connected=False), replace(state, t=0), replace(state, source="poll", raw={"zoom_known": False, "zoom_stable": True})):
        result = create_mode_policy(cfg, "track").decide(context(bad, [det], t=1.))
        assert result.actions["25"].yaw_deg is None


def test_fusion_tracks_and_simulation_truth_cannot_change_image_policy():
    cfg = config()
    state = Telemetry("25", 1., 0, 15)
    a = create_mode_policy(cfg, "track").decide(context(state))
    cfg.simulation["targets"] = [{"id": "truth", "position_m": [1, 2, 3]}]
    truth_like_track = Track("other", 1., (100, 20, 30), (0, 0, 0), tuple(map(tuple, np.eye(6))), 1., 5, "confirmed")
    b = create_mode_policy(cfg, "track").decide(context(state, tracks=[truth_like_track]))
    assert a == b and a.actions["25"].yaw_deg is None


def test_single_camera_without_multistation_calibration_can_track():
    cfg = config()
    cfg.devices[0].calibration_verified = False
    state = Telemetry("25", 1., 0, 15, source="poll", raw={"zoom_known": True, "zoom_stable": True})
    point = np.asarray(cfg.devices[0].position_m) + camera_rotation(state, cfg.devices[0]) @ [100, -10, 5]
    det = detection(cfg, state, point)
    action = create_mode_policy(cfg, "track").decide(context(state, [det])).actions["25"]
    assert action.yaw_deg is not None and action.pitch_deg is not None
    assert next(row for row in mode_catalog(cfg) if row["id"] == "track")["requires_calibration"] is False
