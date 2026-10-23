from __future__ import annotations

import numpy as np

from zr10lab.config import load_config
from zr10lab.models import Telemetry
from zr10lab.research.search_map import PersistentSearchMap
from zr10lab.research.sensing_quality import SensingQualityModel
from zr10lab.research.types import DeviceReadiness


def test_pixels_on_target_increase_with_zoom_and_separate_discovery_monitoring():
    cfg = load_config("configs/research/search_monitor_base.yaml")
    quality = SensingQualityModel(cfg)
    device = cfg.active_devices[0]
    # Representative point close to the angular-shell design range.
    point = np.asarray([170.0, 0.0, 55.0])
    p1 = quality.pixels_on_target(point, device, 1.0)
    p3 = quality.pixels_on_target(point, device, 3.0)
    p6 = quality.pixels_on_target(point, device, 6.0)
    assert p1 < p3 < p6
    assert quality.discovery_valid(point, device, 1.0) is False
    assert quality.discovery_valid(point, device, 3.0) is True
    assert quality.monitor_valid(point, device, 3.0) is False
    assert quality.monitor_valid(point, device, 6.0) is True


def test_angular_search_domain_is_not_static_full_coverage_at_nominal_search_zoom():
    cfg = load_config("configs/research/search_monitor_base.yaml")
    search = PersistentSearchMap(cfg)
    assert len(search.positions) == 13 * 5
    states = {}
    ready = {}
    devices = {d.id: d for d in cfg.active_devices}
    for device in cfg.active_devices:
        states[device.id] = Telemetry(
            device.id, 1.0, 0.0, 0.0, zoom=3.0,
            yaw_rate_dps=0.0, pitch_rate_dps=0.0, connected=True,
        )
        ready[device.id] = DeviceReadiness(device.id, True, 0.0, "ready")
    snap = search.update(1.0, states, ready, devices)
    fraction = float(np.mean(snap.observed_now))
    # The purpose of the angular task domain is to require recurrent steering;
    # four co-oriented cameras must not instantaneously solve the whole search task.
    assert 0.0 < fraction < 0.5


def test_one_x_geometric_view_cannot_reset_long_range_search_cells_without_quality():
    cfg = load_config("configs/research/search_monitor_base.yaml")
    search = PersistentSearchMap(cfg)
    states = {}
    ready = {}
    devices = {d.id: d for d in cfg.active_devices}
    for device in cfg.active_devices:
        states[device.id] = Telemetry(
            device.id, 1.0, 0.0, 0.0, zoom=1.0,
            yaw_rate_dps=0.0, pitch_rate_dps=0.0, connected=True,
        )
        ready[device.id] = DeviceReadiness(device.id, True, 0.0, "ready")
    snap = search.update(1.0, states, ready, devices)
    assert int(snap.observed_now.sum()) == 0
