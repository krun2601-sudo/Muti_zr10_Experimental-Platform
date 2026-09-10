"""跨模块契约回归测试：归一化、执行租约、故障和配置来源路径。"""
import pytest
from dataclasses import replace

from zr10lab.actions import ActionValidator
from zr10lab.config import load_config
from zr10lab.models import Action
from zr10lab.simulation import SimulationWorld


def config():
    cfg = load_config("configs/four_zr10.yaml")
    return cfg


def test_focal_action_survives_runtime_then_simulator_validation():
    cfg = config()
    cfg.action_space["enabled"] = ["focal_length_mm"]
    device = cfg.active_devices[0]
    device.camera["focal_length_table"] = [{"focal_length_mm": 5, "zoom": 1},
                                           {"focal_length_mm": 50, "zoom": 10}]
    world = SimulationWorld(cfg)
    action = Action(device.id, parameters={"focal_length_mm": 10}, issued_t=0, ttl_s=.5)
    # Experiment.process 做第一遍校验；SimulationWorld.advance 做第二遍。
    normalized = ActionValidator(cfg).validate(action, world.states()[device.id], 0, .1)
    world.advance({device.id: normalized}, .1)
    assert world.states()[device.id].zoom > device.initial_zoom


def test_focal_mapping_cannot_bypass_disabled_zoom_capability():
    cfg = config()
    cfg.action_space["enabled"] = ["focal_length_mm"]
    device = cfg.active_devices[0]
    device.capabilities["zoom"] = False
    device.camera["focal_length_table"] = [{"focal_length_mm": 5, "zoom": 1},
                                           {"focal_length_mm": 50, "zoom": 10}]
    world = SimulationWorld(cfg)
    with pytest.raises(ValueError):
        ActionValidator(cfg).validate(Action(device.id, parameters={"focal_length_mm": 10}),
                                      world.states()[device.id], 0, .1)


def test_simulated_continuous_zoom_changes_optical_state():
    cfg = config()
    cfg.action_space["enabled"] = ["zoom_direction"]
    device = cfg.active_devices[0]
    device.capabilities["zoom_direction"] = True
    world = SimulationWorld(cfg)
    world.advance({device.id: Action(device.id, parameters={"zoom_direction": 1}, ttl_s=.5)}, .1)
    assert world.states()[device.id].zoom > device.initial_zoom


def test_simulation_motion_stops_at_lease_expiry_inside_a_step():
    cfg = config()
    device = cfg.active_devices[0]
    world = SimulationWorld(cfg)
    world.advance({device.id: Action(device.id, yaw_deg=90, ttl_s=.1)}, 1.0)
    assert world.states()[device.id].yaw_deg == pytest.approx(device.initial_yaw_deg + device.max_slew_dps * .1)


def test_outage_starting_at_zero_applies_before_first_observation():
    cfg = config()
    device = cfg.active_devices[0]
    cfg.simulation["outages"] = [{"device_id": device.id, "start_s": 0, "end_s": 5}]
    world = SimulationWorld(cfg)
    assert not world.states()[device.id].connected
    assert not any(d.device_id == device.id for d in world.observe())


def test_inherited_relative_weights_resolve_against_defining_yaml(tmp_path):
    import yaml
    cfg = config()
    data = cfg.to_dict()
    data.pop("source")
    data["detector"]["weights"] = "models/drone.pt"
    (tmp_path / "base.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    folder = tmp_path / "variants"
    folder.mkdir()
    child = folder / "child.yaml"
    child.write_text("extends: ../base.yaml\npolicy:\n  name: hold\n", encoding="utf-8")
    inherited = load_config(child)
    assert inherited.detector["weights"] == str((tmp_path / "models" / "drone.pt").resolve())


def test_runtime_excludes_rays_during_known_but_unsettled_zoom():
    from zr10lab.runtime import Experiment
    class Recorder:
        def __init__(self):
            self.rows = []
        def event(self, *args):
            pass
        def write(self, table, t, **values):
            self.rows.append((table, values))
    cfg = config()
    cfg.policy["name"] = "hold"
    cfg.simulation["detection_probability"] = 1.0
    world = SimulationWorld(cfg)
    detections = world.observe()
    assert detections
    states = {key: replace(state, raw={"zoom_known": True, "zoom_stable": False})
              for key, state in world.states().items()}
    recorder = Recorder()
    experiment = Experiment(cfg, recorder)
    experiment.process(0, .1, states, detections)
    assert not any(table == "rays" for table, _ in recorder.rows)
