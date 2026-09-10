"""总控集成边界：假设备和可阻塞算法验证撤销，绝不连接真实网络。"""
import asyncio
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from zr10lab.actions import ActionValidator
from zr10lab.config import load_config
from zr10lab.control_center import ControlCenter
from zr10lab.models import Action, CommandResult, Decision, PolicyContext, Telemetry
from zr10lab.policies import ScanPolicy


def configuration():
    cfg = load_config(Path(__file__).resolve().parents[1] / "configs/four_zr10.yaml")
    cfg.control_center = {"heartbeat_timeout_s": 5., "video_enabled": False}
    return cfg


def wait_until(center, predicate, timeout=3.):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = center.snapshot()
        if predicate(snap):
            return snap
        time.sleep(.01)
    raise AssertionError(center.snapshot())


def send(center, action, **fields):
    result = center.command({"action": action, **fields})
    assert result["ok"], result
    return result


class Unit:
    def __init__(self, device, cfg, sink):
        self.device, self.cfg, self.sink = device, cfg, sink
        self.online = True
        self.latest_action = None
        self.received = []
        self.delay_s = 0.

    def snapshot(self):
        return Telemetry(self.device.id, time.monotonic(), 0, 15, source="fake_hardware", connected=self.online,
                         raw={"zoom_known": False, "zoom_stable": False})

    def _check_action(self, action, now):
        return ActionValidator(self.cfg).validate(action, self.snapshot(), now, .1)

    def submit(self, action):
        self.latest_action = action
        self.received.append(action)
        self.sink(CommandResult(self.device.id, time.monotonic(), action, "sent_unconfirmed", True, False))

    async def cancel_pending(self, reason):
        self.latest_action = None
        await asyncio.sleep(self.delay_s)

    async def close(self):
        self.online = False
        self.latest_action = None

    def start(self):
        self.online = True


class Fleet:
    instances = []
    def __init__(self, cfg, event_sink=None, result_sink=None, telemetry_sink=None):
        self.devices = {d.id: Unit(d, cfg, result_sink) for d in cfg.active_devices}
        self.instances.append(self)

    async def start(self):
        pass

    def states(self):
        return {key: unit.snapshot() for key, unit in self.devices.items()}

    def history(self, key):
        return (self.devices[key].snapshot(),)

    def submit(self, actions):
        for key, action in actions.items():
            self.devices[key].submit(action)

    async def close(self):
        await asyncio.gather(*(unit.close() for unit in self.devices.values()))


@pytest.fixture
def hardware_center(tmp_path, monkeypatch):
    import zr10lab.hardware
    import zr10lab.vision
    monkeypatch.setattr(zr10lab.hardware, "HardwareFleet", Fleet)
    def no_video(*args, **kwargs):
        raise AssertionError("本测试关闭视频、无检测模式，不应打开真实视频")
    monkeypatch.setattr(zr10lab.vision, "VisionPipeline", no_video)
    c = ControlCenter(configuration(), output=tmp_path)
    try:
        send(c, "heartbeat")
        send(c, "start", mode="manual", environment="hardware", armed=True, duration_s=0)
        wait_until(c, lambda s: s["status"] == "running")
        yield c, Fleet.instances[-1]
    finally:
        c.close()


def test_automatic_reconnect_does_not_replay_old_manual_target(hardware_center):
    c, fleet = hardware_center
    unit = fleet.devices["zr10_25"]
    send(c, "manual", device_id="zr10_25", yaw_deg=12)
    wait_until(c, lambda s: any(a.yaw_deg == 12 for a in unit.received))
    unit.online = False
    wait_until(c, lambda s: not s["devices"][0]["connected"])
    unit.online = True
    resumed = wait_until(c, lambda s: s["devices"][0]["connected"])
    assert resumed["devices"][0]["stopped_by_operator"]
    assert resumed["devices"][0]["target"] is None
    count = len(unit.received)
    time.sleep(.25)
    assert not any(a.yaw_deg is not None for a in unit.received[count:])
    # 用户明确提交新的目标后才恢复，旧目标本身从未恢复。
    send(c, "manual", device_id="zr10_25", yaw_deg=3)
    wait_until(c, lambda s: unit.latest_action is not None and unit.latest_action.yaw_deg == 3)


def test_manual_lease_begins_after_slow_stop_ack(hardware_center):
    c, fleet = hardware_center
    unit = fleet.devices["zr10_25"]
    unit.delay_s = .65  # 明显超过每条动作 .5s TTL，模拟慢停机 ACK。
    accepted = send(c, "manual", device_id="zr10_25", yaw_deg=7)["accepted"]
    assert time.monotonic() - accepted["issued_t"] < .3
    assert accepted["ttl_s"] == .5
    wait_until(c, lambda s: any(a.yaw_deg == 7 for a in unit.received))
    unit.delay_s = 0.


def test_estop_during_slow_takeover_cannot_install_action_later(hardware_center):
    c, fleet = hardware_center
    unit = fleet.devices["zr10_25"]
    unit.delay_s = .3
    results = []
    request = threading.Thread(target=lambda: results.append(c.command({"action": "manual", "device_id": "zr10_25", "yaw_deg": 19})))
    request.start()
    time.sleep(.08)
    send(c, "estop")
    request.join(timeout=2)
    assert not request.is_alive() and not results[0]["ok"]
    assert c.snapshot()["status"] == "estopped"
    assert not any(a.yaw_deg == 19 for a in unit.received)
    assert c.snapshot()["devices"][0]["target"] is None
    unit.delay_s = 0.


def test_unknown_or_moving_zoom_is_unavailable_for_spatial_scan():
    cfg = configuration()
    states = {d.id: Telemetry(d.id, 1., 0, 15, source="poll", raw={"zoom_known": False, "zoom_stable": True}) for d in cfg.active_devices}
    context = PolicyContext(1., .1, 0, states)
    assert all(a.yaw_deg is None and a.pitch_deg is None for a in ScanPolicy(cfg).decide(context).actions.values())
    moving = {key: replace(state, raw={"zoom_known": True, "zoom_stable": False}) for key, state in states.items()}
    assert all(a.yaw_deg is None for a in ScanPolicy(cfg).decide(replace(context, devices=moving)).actions.values())


def test_mode_change_during_pending_start_never_mislabels_old_algorithm(tmp_path, monkeypatch):
    import zr10lab.control_modes as modes
    entered, release = threading.Event(), threading.Event()
    original = modes.create_mode_policy
    def waiting(cfg, mode_id, reload=False):
        entered.set()
        assert release.wait(3)
        return original(cfg, mode_id, reload)
    monkeypatch.setattr(modes, "create_mode_policy", waiting)
    c = ControlCenter(configuration(), output=tmp_path)
    try:
        send(c, "heartbeat")
        send(c, "start", mode="manual", duration_s=0)
        assert entered.wait(1)
        rejected = c.command({"action": "mode", "mode": "scan"})
        assert not rejected["ok"]
        assert c.snapshot()["mode"] == "manual"
        release.set()
        wait_until(c, lambda s: s["status"] == "running")
    finally:
        release.set()
        c.close()


def test_late_policy_result_cannot_send_after_stop(hardware_center, monkeypatch):
    c, fleet = hardware_center
    entered, release = threading.Event(), threading.Event()
    class DelayedPolicy:
        def reset(self):
            pass
        def decide(self, ctx):
            entered.set()
            assert release.wait(3)
            return Decision({d: Action(d, yaw_deg=33, issued_t=ctx.t) for d in ctx.devices})
    c._experiment.policy = DelayedPolicy()
    try:
        assert entered.wait(1)
        send(c, "stop")
        counts = {key: len(unit.received) for key, unit in fleet.devices.items()}
        release.set()
        time.sleep(.15)
        assert all(len(unit.received) == counts[key] for key, unit in fleet.devices.items())
        assert not any(a.yaw_deg == 33 for unit in fleet.devices.values() for a in unit.received)
        assert c.snapshot()["status"] == "stopped"
    finally:
        release.set()
