from __future__ import annotations

import numpy as np

from zr10lab.config import load_config
from zr10lab.geometry import project_world_points
from zr10lab.models import Telemetry
from zr10lab.research.search_map import PersistentSearchMap
from zr10lab.research.sensing_quality import SensingQualityModel
from zr10lab.research.types import DeviceReadiness


def test_pixels_on_target_increase_with_zoom_and_separate_discovery_monitoring():
    cfg = load_config("configs/research/search_monitor_base.yaml")
    quality = SensingQualityModel(cfg)
    device = cfg.active_devices[0]
    # A near-limit point for zr10_25: about 99.4 m away but still inside the ROI.
    point = np.asarray([40.0, 20.0, 60.0])
    p1 = quality.pixels_on_target(point, device, 1.0)
    p3 = quality.pixels_on_target(point, device, 3.0)
    p4 = quality.pixels_on_target(point, device, 4.0)
    assert p1 < p3 < p4
    assert quality.discovery_valid(point, device, 1.0) is False
    assert quality.discovery_valid(point, device, 3.0) is True
    assert quality.monitor_valid(point, device, 3.0) is False
    assert quality.monitor_valid(point, device, 4.0) is True


def test_cartesian_search_domain_is_not_static_full_coverage_at_nominal_search_zoom():
    cfg = load_config("configs/research/search_monitor_base.yaml")
    search = PersistentSearchMap(cfg)
    assert len(search.positions) == 3 * 7 * 3
    states = {}
    ready = {}
    devices = {d.id: d for d in cfg.active_devices}
    for device in cfg.active_devices:
        states[device.id] = Telemetry(
            device.id, 1.0, device.initial_yaw_deg, device.initial_pitch_deg, zoom=3.0,
            yaw_rate_dps=0.0, pitch_rate_dps=0.0, connected=True,
        )
        ready[device.id] = DeviceReadiness(device.id, True, 0.0, "ready")
    snap = search.update(1.0, states, ready, devices)
    fraction = float(np.mean(snap.observed_now))
    # Initial inward-facing cameras still require recurrent steering to cover the box.
    assert 0.0 < fraction < 0.5


def test_one_x_geometric_view_does_not_reset_cells_that_fail_quality():
    cfg = load_config("configs/research/search_monitor_base.yaml")
    search = PersistentSearchMap(cfg)
    states = {}
    ready = {}
    devices = {d.id: d for d in cfg.active_devices}
    for device in cfg.active_devices:
        states[device.id] = Telemetry(
            device.id, 1.0, device.initial_yaw_deg, device.initial_pitch_deg, zoom=1.0,
            yaw_rate_dps=0.0, pitch_rate_dps=0.0, connected=True,
        )
        ready[device.id] = DeviceReadiness(device.id, True, 0.0, "ready")
    snap = search.update(1.0, states, ready, devices)
    blocked_by_quality = 0
    for device in cfg.active_devices:
        geometric = project_world_points(search.positions, states[device.id], device)
        blocked_by_quality += sum(
            pixel is not None and not search.quality.discovery_valid(point, device, 1.0)
            for point, pixel in zip(search.positions, geometric)
        )
    assert 0 < int(snap.observed_now.sum()) < len(search.positions)
    assert blocked_by_quality > 0
