"""视场展示遵循相机几何和真实反馈可用性，不把绘图长度当成量程。"""
import json
from dataclasses import replace

import cv2
import numpy as np
import pytest

from zr10lab.config import DeviceConfig, LabConfig
from zr10lab.geometry import camera_rotation, intrinsics_at_zoom
from zr10lab.models import Telemetry, Track
from zr10lab.scene import build_scene


def config():
    d = DeviceConfig("25", position_m=(2, -3, 1), mount_rpy_deg=(5, -8, 20), calibration_verified=True,
                    camera={"image_size": [1280, 720], "intrinsics": [
                        dict(zoom=1, fx=900, fy=850, cx=590, cy=330, dist=[0] * 5),
                        dict(zoom=10, fx=9000, fy=8500, cx=592, cy=328, dist=[0] * 5)]})
    return LabConfig([d], policy={"roi": {"x": [0, 200], "y": [-50, 50], "z": [0, 100]}})


def test_frustum_corners_reproject_exact_sensor_boundary_with_mount_roll():
    cfg = config()
    d = cfg.devices[0]
    state = Telemetry("25", 2., 28, 16, roll_deg=31)
    scene = build_scene(cfg, {"25": state}, (), 2., range_m=150.)
    item = scene["devices"][0]
    fov = item["frustum"]
    assert scene["coordinate_system"] == "ENU" and scene["up_axis"] == "z"
    assert item["valid"] and item["source"] == "simulation"
    points = np.asarray(fov["corners"])
    local = (points - d.position_m) @ camera_rotation(state, d)
    np.testing.assert_allclose(local[:, 0], 150.)
    optical = local[:, [1, 2, 0]] * [-1, -1, 1]
    k = intrinsics_at_zoom(d, 1)
    pixels, _ = cv2.projectPoints(optical, np.zeros(3), np.zeros(3), k.K, np.asarray(k.dist))
    np.testing.assert_allclose(pixels.reshape(-1, 2), [[0, 0], [1279, 0], [1279, 719], [0, 719]], atol=1e-8)
    np.testing.assert_allclose(fov["center_direction"], camera_rotation(state, d) @ [1, 0, 0])
    # off-axis 主点意味着四角均值与光轴截断点不重合，不能强行对称造锥。
    assert np.linalg.norm(points.mean(axis=0) - np.asarray(d.position_m) - np.asarray(fov["center_direction"]) * 150) > 1
    json.dumps(scene, allow_nan=False)


def test_zoom_narrows_measured_fov_without_millimeter_fabrication():
    cfg = config()
    state = Telemetry("25", 1., 0, 15)
    wide = build_scene(cfg, {"25": state}, [], 1.)["devices"][0]
    tight = build_scene(cfg, {"25": replace(state, zoom=10)}, [], 1.)["devices"][0]
    assert tight["frustum"]["hfov_deg"] < wide["frustum"]["hfov_deg"] / 5
    assert tight["focal_length_mm"] is None and tight["focal_length_source"] == "unknown"
    cfg.devices[0].camera["focal_length_table"] = [{"zoom": 1, "focal_length_mm": 5.1}, {"zoom": 10, "focal_length_mm": 51.}]
    measured = build_scene(cfg, {"25": replace(state, zoom=5.5)}, [], 1.)["devices"][0]
    assert measured["focal_length_mm"] == pytest.approx(28.05)
    assert measured["focal_length_source"] == "calibration_table_interpolation"


@pytest.mark.parametrize("update, reason", [
    ({"connected": False}, "offline"), ({"t": 0}, "telemetry_stale"),
    ({"raw": {"zoom_known": False, "zoom_stable": True}}, "zoom_unknown"),
    ({"raw": {"zoom_known": True, "zoom_stable": False}}, "zoom_unstable"),
    ({"raw": {"zoom_known": True, "zoom_stable": True, "zoom_t": -2}}, "zoom_stale"),
    ({"device_id": "26"}, "device_id_mismatch"),
])
def test_hardware_invalid_feedback_draws_no_valid_frustum(update, reason):
    cfg = config()
    state = Telemetry("25", 1., 10, 15, source="poll", raw={"zoom_known": True, "zoom_stable": True})
    item = build_scene(cfg, {"25": replace(state, **update)}, [], 1.)["devices"][0]
    assert item["reason"] == reason and not item["valid"] and item["frustum"] is None
    assert item["position_m"] == [2., -3., 1.]


def test_unverified_hardware_and_configuration_preview_are_distinct():
    cfg = config()
    cfg.devices[0].calibration_verified = False
    state = Telemetry("25", 1., 10, 15, source="poll", raw={"zoom_known": True, "zoom_stable": True})
    actual = build_scene(cfg, {"25": state}, [], 1., preview=True)["devices"][0]
    assert actual["reason"] == "calibration_unverified" and actual["frustum"] is None
    initial = build_scene(cfg, {}, [], 1., preview=True)["devices"][0]
    assert not initial["valid"] and not initial["connected"] and initial["source"] == "configuration_preview"
    assert initial["frustum"]["is_preview"] and initial["frustum"]["range_is_visualization_only"]
    no_preview = build_scene(cfg, {}, [], 1.)["devices"][0]
    assert no_preview["frustum"] is None and no_preview["reason"] == "unavailable"


def test_range_is_only_axis_depth_and_does_not_remove_localized_track():
    cfg = config()
    state = Telemetry("25", 1., 0, 15)
    track = Track("t1", 1., (1000, 10, 30), (1, 2, 0), tuple(map(tuple, np.eye(6))), 1., 3, "confirmed", ("25", "26"))
    small = build_scene(cfg, {"25": state}, [track], 1., range_m=20.)
    large = build_scene(cfg, {"25": state}, [track], 1., range_m=200.)
    assert small["tracks"] == large["tracks"] and small["tracks"][0]["position_m"] == [1000., 10., 30.]
    assert small["devices"][0]["frustum"]["range_definition"] == "optical_axis_depth"
    assert small["range_is_visualization_only"]
    delta1 = np.asarray(small["devices"][0]["frustum"]["corners"]) - cfg.devices[0].position_m
    delta2 = np.asarray(large["devices"][0]["frustum"]["corners"]) - cfg.devices[0].position_m
    np.testing.assert_allclose(delta2, 10 * delta1)
    predicted = build_scene(cfg, {}, [replace(track, measured=False, status="coasting")], 1.)["tracks"][0]
    assert predicted["source"] == "prediction" and not predicted["measured"]


def test_distortion_boundary_is_sampled_and_invalid_intrinsics_are_rejected():
    cfg = config()
    cfg.devices[0].camera["intrinsics"][0]["dist"] = [-.06, .005, .001, -.002, 0]
    state = Telemetry("25", 1., 12, 15, roll_deg=-22)
    item = build_scene(cfg, {"25": state}, [], 1.)["devices"][0]
    assert len(item["frustum"]["boundary"]) == 36
    cfg.devices[0].camera["intrinsics"] = []
    invalid = build_scene(cfg, {"25": state}, [], 1.)["devices"][0]
    assert not invalid["valid"] and invalid["reason"].startswith("invalid_geometry")
    with pytest.raises(ValueError):
        build_scene(cfg, {}, [], 1., range_m=float("nan"))


def test_world_track_from_unverified_hardware_cannot_appear_as_valid_localization():
    cfg = config()
    cfg.devices[0].calibration_verified = False
    state = Telemetry("25", 1., 0, 15, source="poll", raw={"zoom_known": True, "zoom_stable": True})
    track = Track("bad", 1., (100, 20, 30), (0, 0, 0), tuple(map(tuple, np.eye(6))), 1., 3, "confirmed", ("25", "26"))
    row = build_scene(cfg, {"25": state}, [track], 1.)["tracks"][0]
    assert not row["valid"] and row["reason"] == "unverified_localization_stations"


def test_hardware_coasting_with_no_current_measurements_remains_labeled_prediction():
    cfg = config()
    cfg.devices.append(replace(cfg.devices[0], id="26", position_m=(2, 20, 1)))
    state = Telemetry("25", 1., 0, 15, source="poll", raw={"zoom_known": True, "zoom_stable": True})
    track = Track("coast", 1., (100, 20, 30), (0, 0, 0), tuple(map(tuple, np.eye(6))), .9, 3, "coasting", (), measured=False)
    row = build_scene(cfg, {"25": state}, [track], 1.)["tracks"][0]
    assert row["valid"] and row["source"] == "prediction" and not row["measured"] and row["device_ids"] == []
