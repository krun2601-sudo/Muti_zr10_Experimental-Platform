"""以已知物理关系验证坐标、非中心像素和几何拒绝条件。"""
from dataclasses import replace

import numpy as np
import pytest

from zr10lab.config import DeviceConfig
from zr10lab.geometry import (camera_rotation, intrinsics_at_zoom, pixel_to_world_ray,
    project_world_point, project_world_points, rotation_matrix, triangulate_rays, world_to_gimbal_angles)
from zr10lab.models import Detection, Ray, Telemetry


def camera_config():
    return DeviceConfig(id="25", position_m=(2, -3, 1), mount_rpy_deg=(5, -8, 20), camera={
        "image_size": [1920, 1080],
        "intrinsics": [dict(zoom=1, fx=1200, fy=1180, cx=960, cy=540, dist=[-.12, .03, .001, -.002, 0]),
                       dict(zoom=10, fx=11000, fy=10900, cx=962, cy=538, dist=[-.05, .01, 0, 0, 0])],
    })


def rays_for(point, t=1.):
    origins = [(-10, -8, 0), (10, -8, 0), (10, 8, 1), (-10, 8, 1)]
    result = []
    for i, origin in enumerate(origins):
        direction = np.asarray(point) - origin
        direction /= np.linalg.norm(direction)
        result.append(Ray(str(25 + i), f"frame1:det{i}", t, origin, tuple(direction)))
    return result


def test_axis_convention_and_orthonormality():
    np.testing.assert_allclose(rotation_matrix(90, 0) @ [1, 0, 0], [0, 1, 0], atol=1e-12)
    np.testing.assert_allclose(rotation_matrix(0, 90) @ [1, 0, 0], [0, 0, 1], atol=1e-12)
    r = rotation_matrix(32, 18, -12)
    np.testing.assert_allclose(r.T @ r, np.eye(3), atol=1e-12)
    assert np.linalg.det(r) == pytest.approx(1.)


def test_mount_inverse_points_optical_center():
    cfg = camera_config()
    point = np.array([32., 24., 40.])
    yaw, pitch = world_to_gimbal_angles(point, cfg)
    state = Telemetry("25", 1., yaw, pitch, zoom=1)
    pixel = project_world_point(point, state, cfg)
    np.testing.assert_allclose(pixel, [960, 540], atol=1e-7)
    expected = point - cfg.position_m
    expected /= np.linalg.norm(expected)
    np.testing.assert_allclose(camera_rotation(state, cfg) @ [1, 0, 0], expected, atol=1e-10)


def test_distorted_noncentral_target_round_trip_with_roll():
    cfg = camera_config()
    state = Telemetry("25", 1., 30, 18, roll_deg=13, zoom=1.)
    point = np.asarray(cfg.position_m) + camera_rotation(state, cfg) @ np.array([60., -18., 10.])
    u, v = project_world_point(point, state, cfg)
    assert u > 960 and v < 540
    det = Detection("25", 1, 1., (u - 10, v - 10, u + 10, v + 10), local_id="a")
    ray = pixel_to_world_ray(det, state, cfg)
    expected = point - cfg.position_m
    expected /= np.linalg.norm(expected)
    np.testing.assert_allclose(ray.direction, expected, atol=1e-7)
    with pytest.raises(ValueError, match="分辨率"):
        pixel_to_world_ray(replace(det, image_size=(1280, 720)), state, cfg)


def test_zoom_interpolation_and_uncalibrated_rejection():
    cfg = camera_config()
    intrinsics = intrinsics_at_zoom(cfg, 5.5)
    assert intrinsics.fx == pytest.approx((1200 + 11000) / 2)
    assert intrinsics.cx == pytest.approx(961)
    assert intrinsics.dist[0] == pytest.approx(-.085)
    with pytest.raises(ValueError, match="超出"):
        intrinsics_at_zoom(cfg, 11)


def test_exact_triangulation_and_positive_covariance():
    point = (5., 25., 40.)
    result = triangulate_rays(rays_for(point))
    np.testing.assert_allclose(result.position, point, atol=1e-9)
    assert result.residual_m < 1e-9
    assert len(result.device_ids) == 4
    assert np.all(np.linalg.eigvalsh(result.covariance) > 0)


def test_weak_geometry_time_uncertainty_and_station_exclusivity():
    a = Ray("25", "a", 1., (0, 0, 0), (0, 1, 0))
    b = Ray("26", "b", 1., (10, 0, 0), (0, 1, 0))
    with pytest.raises(ValueError, match="weak_geometry"):
        triangulate_rays([a, b])
    rays = rays_for((0., 20., 40.))
    with pytest.raises(ValueError, match="duplicate_station"):
        triangulate_rays([rays[0], rays[0]])
    with pytest.raises(ValueError, match="time_uncertainty"):
        triangulate_rays([replace(rays[0], time_uncertainty_s=.25), rays[1]])
    with pytest.raises(ValueError, match="time_skew"):
        triangulate_rays([replace(rays[0], t=1.1), rays[1]])
    with pytest.raises(ValueError, match="behind_camera"):
        triangulate_rays([replace(r, direction=tuple(-np.asarray(r.direction))) for r in rays[:2]])


def test_one_station_and_out_of_range_are_rejected():
    rays = rays_for((0., 20., 40.))
    with pytest.raises(ValueError, match="insufficient_stations"):
        triangulate_rays(rays[:1])
    with pytest.raises(ValueError, match="range_limit"):
        triangulate_rays(rays[:2], {"max_range_m": 10})


def test_exposure_uncertainty_inflates_spatial_covariance():
    rays = rays_for((0., 20., 40.))
    exact_time = triangulate_rays(rays)
    uncertain_time = triangulate_rays([replace(ray, time_uncertainty_s=.15) for ray in rays])
    np.testing.assert_allclose(uncertain_time.position, exact_time.position, atol=1e-8)
    assert uncertain_time.time_span_s == 0
    assert np.trace(uncertain_time.covariance) > 100 * np.trace(exact_time.covariance)


def test_batch_projection_preserves_order_and_invalid_points():
    cfg = camera_config()
    state = Telemetry("25", 1., 30, 18, zoom=1)
    points = [np.asarray(cfg.position_m) + camera_rotation(state, cfg) @ p
              for p in ([30., 0., 0.], [-30., 0., 0.], [30., -2., 1.], [30., 1000., 0.])]
    projected = project_world_points(points, state, cfg)
    np.testing.assert_allclose(projected[0], [960, 540], atol=1e-7)
    assert projected[1] is None and projected[3] is None
    np.testing.assert_allclose(projected[2], project_world_point(points[2], state, cfg))
    assert project_world_points([], state, cfg) == []


def test_moving_gimbal_timing_error_inflates_angular_uncertainty():
    cfg = camera_config()
    det = Detection("25", 1, 1., (950, 530, 970, 550), local_id="a", time_uncertainty_s=.1)
    stationary = Telemetry("25", 1., 0, 0, zoom=1)
    moving = replace(stationary, yaw_rate_dps=20, raw={"pose_time_error_s": .05})
    ray_stationary = pixel_to_world_ray(det, stationary, cfg)
    ray_moving = pixel_to_world_ray(det, moving, cfg)
    assert ray_stationary.angular_std_deg == pytest.approx(.15)
    assert ray_moving.angular_std_deg > 3
