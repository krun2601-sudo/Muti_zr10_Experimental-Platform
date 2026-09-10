"""不借助真值身份的多目标关联与轨迹生命周期测试。"""
from dataclasses import replace

import numpy as np
import pytest

from zr10lab.fusion import FusionEngine
from zr10lab.models import Ray


ORIGINS = [(-12., -12., 0.), (12., -12., 0.), (12., 12., 0.), (-12., 12., 0.)]


def make_rays(points, t, frame):
    rays = []
    for station, origin in enumerate(ORIGINS):
        for index, point in enumerate(points):
            direction = np.asarray(point, dtype=float) - origin
            direction /= np.linalg.norm(direction)
            # 每个相机的本地检测编号每帧排列；同类目标均 class_id=0。
            local = (index + station + frame) % len(points)
            rays.append(Ray(str(25 + station), f"{frame}:{local}", t, origin, tuple(direction), angular_std_deg=.1))
    np.random.default_rng(frame).shuffle(rays)
    return rays


def test_same_class_multiple_targets_have_exclusive_measurements():
    engine = FusionEngine({"max_residual_m": .3})
    points = [(18., 28., 50.), (-20., 5., 38.)]
    tracks, locs, diag = engine.update(make_rays(points, 0, 0), 0.)
    assert len(locs) == len(tracks) == 2
    all_ids = [(d, local) for loc in locs for d, local in zip(loc.device_ids, loc.detection_ids)]
    assert len(all_ids) == len(set(all_ids))
    for point in points:
        assert min(np.linalg.norm(np.asarray(loc.position) - point) for loc in locs) < 1e-7
    assert diag["localized_count"] == 2


def test_constant_velocity_estimation_and_observation_vs_coasting():
    engine = FusionEngine({"max_residual_m": .3, "track_timeout_s": .7, "confirmation_hits": 3})
    velocity = np.array([.7, -.3, .15])
    identity = None
    for frame in range(30):
        t = frame * .1
        points = [np.array([10., 25., 45.]) + velocity * t]
        tracks, locs, _ = engine.update(make_rays(points, t, frame), t)
        assert len(tracks) == len(locs) == 1
        identity = identity or tracks[0].track_id
        assert tracks[0].track_id == identity
    np.testing.assert_allclose(tracks[0].velocity, velocity, atol=.06)
    assert tracks[0].status == "confirmed"
    tracks, locs, _ = engine.update([], 3.1)
    assert not locs and not tracks[0].measured and tracks[0].status == "coasting"
    assert tracks[0].device_ids == ()
    tracks, locs, diag = engine.update([], 3.7)
    assert not tracks and not locs and diag["deleted_track_ids"] == [identity]


def test_duplicate_frame_does_not_increment_hits_or_localize_again():
    engine = FusionEngine()
    rays = make_rays([(10., 20., 40.)], 0., 0)
    tracks, locs, _ = engine.update(rays, 0.)
    assert tracks[0].hits == 1 and len(locs) == 1
    tracks, locs, diag = engine.update(rays, .1)
    assert tracks[0].hits == 1 and not locs and not tracks[0].measured
    assert diag["duplicate_rays"] == 4


def test_async_arrival_pairs_buffered_observations_once():
    engine = FusionEngine()
    rays = make_rays([(10., 20., 40.)], 0., 0)
    first = [r for r in rays if r.device_id == "25"]
    second = [r for r in rays if r.device_id == "26"]
    tracks, locs, _ = engine.update(first, .02)
    assert not tracks and not locs
    tracks, locs, _ = engine.update(second, .04)
    assert len(tracks) == len(locs) == 1
    tracks, locs, _ = engine.update(first + second, .06)
    assert not locs and tracks[0].hits == 1


def test_time_skew_stale_and_backwards_input():
    engine = FusionEngine({"max_time_skew_s": .02})
    rays = make_rays([(10., 20., 40.)], 0., 0)
    a = next(r for r in rays if r.device_id == "25")
    b = replace(next(r for r in rays if r.device_id == "26"), t=.1)
    tracks, locs, diag = engine.update([a, b], .1)
    assert not tracks and not locs and diag["rejections"]["time_skew"] >= 1
    with pytest.raises(ValueError, match="单调"):
        engine.update([], .05)


def test_coplanar_geometry_identity_ambiguity_is_reported():
    engine = FusionEngine({"min_ray_angle_deg": .2, "max_residual_m": .1})
    points = [(-3., 0., 25.), (3., 0., 35.)]
    rays = []
    for station, origin in enumerate([(-10., 0., 0.), (10., 0., 0.)]):
        for index, point in enumerate(points):
            direction = np.asarray(point) - origin
            direction /= np.linalg.norm(direction)
            rays.append(Ray(str(station), str(index), 0., origin, tuple(direction)))
    tracks, locs, diag = engine.update(rays, 0.)
    assert len(locs) == 2
    assert diag["ambiguous_count"] > 0


def test_nearby_distinct_targets_can_both_start_tracks():
    engine = FusionEngine({"max_residual_m": .05})
    points = [(10., 20., 40.), (14., 23., 47.)]
    tracks, locs, _ = engine.update(make_rays(points, 0., 0), 0.)
    assert len(tracks) == len(locs) == 2


def test_invalid_fusion_budget_and_covariance_settings_fail_early():
    with pytest.raises(ValueError, match="max_hypotheses"):
        FusionEngine({"max_hypotheses": 0})
    with pytest.raises(ValueError, match="initial_velocity_std_mps"):
        FusionEngine({"initial_velocity_std_mps": float("nan")})
