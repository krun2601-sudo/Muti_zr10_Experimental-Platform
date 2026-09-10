"""已知控制点外参拟合：恢复真实安装旋转/位置，并拒绝退化布置。"""
import numpy as np
import pytest
import json
from pathlib import Path

from zr10lab.calibration import fit_mount_pose, main
from zr10lab.geometry import rotation_matrix


def synthetic_controls():
    points = np.array([[10., 20., 30.], [-20., 10., 40.], [30., -10., 20.],
                       [-10., -20., 50.], [5., 25., 60.], [40., 30., 15.],
                       [-30., 35., 20.], [20., -30., 60.]])
    ypr = np.array([[20., 30., 1.], [45., 25., -2.], [-30., 20., 3.],
                    [-60., 40., 0.], [70., 35., 2.], [10., 10., -1.],
                    [90., 15., 0.], [-50., 50., 1.]])
    mount = np.array([12., -7., 4.])
    position = np.array([2., -1., .8])
    rays = []
    for point, angle in zip(points, ypr):
        direction = point - position
        direction /= np.linalg.norm(direction)
        rays.append(rotation_matrix(*angle).T @ rotation_matrix(*mount).T @ direction)
    return points, ypr, mount, position, rays


def test_known_position_recovers_mount_rotation():
    points, ypr, mount, position, rays = synthetic_controls()
    result = fit_mount_pose(points, rays, ypr, position)
    assert result.success
    np.testing.assert_allclose(result.mount_ypr_deg, mount, atol=1e-5)
    assert result.rms_angle_deg < 1e-5


def test_mount_and_position_offset_are_jointly_recovered():
    points, ypr, mount, position, rays = synthetic_controls()
    nominal = position + [0.5, -.3, .2]
    result = fit_mount_pose(points, rays, ypr, nominal, fit_position=True)
    assert result.success
    np.testing.assert_allclose(result.mount_ypr_deg, mount, atol=1e-4)
    np.testing.assert_allclose(result.position_enu_m, position, atol=1e-4)
    np.testing.assert_allclose(result.position_offset_m, [-.5, .3, -.2], atol=1e-4)


def test_degenerate_controls_are_not_certified():
    points = [[10., 0., 0.]] * 6
    result = fit_mount_pose(points, [[1., 0., 0.]] * 6, [[0., 0., 0.]] * 6,
                            [0., 0., 0.], fit_position=True)
    assert not result.success
    with pytest.raises(ValueError, match="至少需要"):
        fit_mount_pose(points[:2], [[1., 0., 0.]] * 2, [[0., 0., 0.]] * 2, [0, 0, 0])


def test_calibration_command_processes_example_csv(tmp_path):
    project = Path(__file__).resolve().parents[1]
    output = tmp_path / "mount_result.json"
    assert main(["mount", "--config", str(project / "configs/four_zr10.yaml"),
                 "--device", "zr10_25", "--csv", str(project / "examples/calibration_controls_example.csv"),
                 "--output", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["success"] and result["rms_angle_deg"] < 1e-5
    np.testing.assert_allclose(result["config_device_patch"]["mount_rpy_deg"], [0, 25, 0], atol=1e-5)
    assert not result["config_device_patch"]["calibration_verified"]
