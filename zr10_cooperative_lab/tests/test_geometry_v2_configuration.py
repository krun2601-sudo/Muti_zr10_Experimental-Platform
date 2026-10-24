from __future__ import annotations

from pathlib import Path

import numpy as np

from zr10lab.config import load_config
from zr10lab.geometry import world_to_gimbal_angles
from zr10lab.research.search_map import PersistentSearchMap
from zr10lab.research.target_field import VirtualTargetField


EXPECTED_ROI = {"x": [10, 40], "y": [-40, 40], "z": [10, 60]}
EXPECTED_DEVICES = {
    "zr10_25": ((0, -50, 2), (0, 55, 63.434948823)),
    "zr10_26": ((0, 50, 2), (0, 55, -63.434948823)),
    "zr10_27": ((50, -50, 2), (0, 55, 116.565051177)),
    "zr10_28": ((50, 50, 2), (0, 55, -116.565051177)),
}


def test_geometry_v2_has_one_canonical_device_and_roi_configuration():
    cfg = load_config("configs/research/search_monitor_base.yaml")
    assert cfg.policy["roi"] == EXPECTED_ROI
    assert cfg.policy["research"]["scenario"]["roi"] == EXPECTED_ROI
    assert cfg.policy["research"]["search"]["roi"] == EXPECTED_ROI
    assert cfg.policy["research"]["sensing"]["max_effective_range_m"] == 100.0
    assert cfg.fusion["max_range_m"] == 100
    assert cfg.policy["research"]["search"]["domain"]["type"] == "cartesian"
    assert cfg.policy["research"]["search"]["grid"] == [3, 7, 3]

    assert set(EXPECTED_DEVICES) == {d.id for d in cfg.active_devices}
    for device in cfg.active_devices:
        position, mount = EXPECTED_DEVICES[device.id]
        assert tuple(device.position_m) == position
        assert tuple(device.mount_rpy_deg) == mount
        assert device.initial_yaw_deg == 0
        assert device.initial_pitch_deg == -25
        assert device.calibration_verified is False


def test_every_search_cell_is_range_and_gimbal_reachable_from_at_least_two_devices():
    cfg = load_config("configs/research/search_monitor_base.yaml")
    search = PersistentSearchMap(cfg)
    assert len(search.positions) == 63
    for point in search.positions:
        reachable = 0
        for device in cfg.active_devices:
            distance = float(np.linalg.norm(point - np.asarray(device.position_m, dtype=float)))
            yaw, pitch = world_to_gimbal_angles(point, device)
            if (distance <= 100.0 + 1e-9
                    and device.yaw_limits_deg[0] <= yaw <= device.yaw_limits_deg[1]
                    and device.pitch_limits_deg[0] <= pitch <= device.pitch_limits_deg[1]):
                reachable += 1
        assert reachable >= 2, (point.tolist(), reachable)


def test_all_research_scenarios_use_geometry_v2_and_have_active_truth():
    for path in sorted(Path("configs/research/scenarios").glob("S*.yaml")):
        cfg = load_config(path)
        scenario = cfg.policy["research"]["scenario"]
        assert scenario["roi"] == EXPECTED_ROI, path
        field = VirtualTargetField(cfg)
        for row in field.targets:
            start = float(row.get("start_s", 0.0))
            end = min(float(row.get("end_s", cfg.system["duration_s"])),
                      float(cfg.system["duration_s"]))
            samples = np.linspace(start, end, 101)
            assert any(str(row["id"]) in field.truth(float(t)) for t in samples), (path, row["id"])
