"""控制中心行为测试：全部离线，任何硬件测试都使用假控制器。"""
import asyncio
import csv
import json
import os
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from zr10lab.actions import ActionValidator
from zr10lab.config import load_config
from zr10lab.control_center import ControlCenter
from zr10lab.models import Action, CommandResult, Decision, Telemetry, Track


ROOT = Path(__file__).resolve().parents[1]


def configuration():
    cfg = load_config(ROOT / "configs/four_zr10.yaml")
    for device in cfg.devices:
        device.calibration_verified = False
    cfg.control_center = {"heartbeat_timeout_s": 2., "preview_fps": 6}
    return cfg


def wait_for(center, predicate, timeout=3):
    end = time.monotonic()+timeout
    while time.monotonic() < end:
        snap = center.snapshot()
        if predicate(snap):
            return snap
        time.sleep(.02)
    raise AssertionError(center.snapshot())


def send(center, action, **values):
    result = center.command({"action": action, **values})
    assert result["ok"], result
    return result


@pytest.fixture
def center(tmp_path):
    instance = ControlCenter(configuration(), output=tmp_path)
    instance.start()
    try:
        yield instance
    finally:
        instance.close()


def begin(center, mode="manual", **kwargs):
    send(center, "heartbeat")
    send(center, "start", mode=mode, duration_s=0, **kwargs)
    return wait_for(center, lambda s: s["status"] == "running")


def test_service_start_is_idle_and_requires_live_browser(center):
    assert center.snapshot()["status"] == "idle"
    assert not center.command({"action": "start"})["ok"]
    assert center.snapshot()["session_path"] is None


def test_simulation_manual_target_pause_resume_and_csv(center):
    begin(center)
    initial = center.snapshot()["devices"][0]["feedback"]["yaw_deg"]
    send(center, "manual", device_id="zr10_25", yaw_deg=initial+3)
    snap = wait_for(center, lambda s: s["devices"][0]["feedback"]["yaw_deg"] == pytest.approx(initial+3))
    assert snap["devices"][0]["manual_override"]
    assert snap["devices"][0]["command"]["ack"] is False
    assert snap["devices"][0]["command"]["status"] == "simulated"
    send(center, "pause")
    assert not center.snapshot()["devices"][0]["manual_override"]
    send(center, "heartbeat")
    send(center, "resume")
    send(center, "stop")
    path = Path(center.snapshot()["session_path"])
    with (path/"actions.csv").open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert any(row["reason"] == "operator_manual" for row in rows)
    assert json.loads((path/"metadata.json").read_text(encoding="utf-8"))["mode"] == "sim"


def test_invalid_actions_do_not_replace_valid_target(center):
    begin(center)
    send(center, "manual", device_id="zr10_25", yaw_deg=4)
    target = center.snapshot()["devices"][0]["target"]
    assert not center.command({"action": "manual", "device_id": "zr10_25", "yaw_deg": 999})["ok"]
    assert not center.command({"action": "manual", "device_id": "zr10_25", "zoom": 2})["ok"]
    assert not center.command({"action": "manual", "device_id": "zr10_25", "parameters": {"photo": True}})["ok"]
    assert center.snapshot()["devices"][0]["target"]["yaw_deg"] == target["yaw_deg"]


def test_estop_latches_and_old_actions_never_resume(center):
    begin(center)
    send(center, "manual", device_id="zr10_25", yaw_deg=50)
    wait_for(center, lambda s: s["devices"][0]["feedback"]["yaw_deg"] > 0)
    send(center, "estop")
    assert center.snapshot()["status"] == "estopped"
    paused = center.snapshot()["devices"][0]["feedback"]["yaw_deg"]
    time.sleep(.25)
    assert center.snapshot()["devices"][0]["feedback"]["yaw_deg"] == paused
    assert not center.command({"action": "resume"})["ok"]
    assert not center.command({"action": "manual", "device_id": "zr10_25", "yaw_deg": 0})["ok"]
    send(center, "reset_estop")
    assert center.snapshot()["status"] == "paused"
    send(center, "heartbeat")
    send(center, "resume")
    time.sleep(.25)
    assert center.snapshot()["devices"][0]["feedback"]["yaw_deg"] == paused


def test_browser_timeout_pauses_and_reconnect_does_not_resume(tmp_path):
    cfg = configuration()
    cfg.control_center["heartbeat_timeout_s"] = .15
    c = ControlCenter(cfg, output=tmp_path)
    try:
        begin(c)
        wait_for(c, lambda s: s["status"] == "paused")
        send(c, "heartbeat")
        assert c.snapshot()["status"] == "paused"
        assert any(e["payload"].get("reason") == "browser_heartbeat_expired" for e in c.snapshot()["events"])
    finally:
        c.close()


def test_stop_device_and_release_are_explicit(center):
    begin(center)
    send(center, "manual", device_id="zr10_25", yaw_deg=10)
    send(center, "stop_device", device_id="zr10_25")
    assert center.snapshot()["devices"][0]["stopped_by_operator"]
    send(center, "release_manual", device_id="zr10_25")
    assert not center.snapshot()["devices"][0]["manual_override"]
    send(center, "disconnect", device_id="zr10_25")
    wait_for(center, lambda s: not s["devices"][0]["connected"])
    assert not center.command({"action": "manual", "device_id": "zr10_25", "yaw_deg": 1})["ok"]
    send(center, "connect", device_id="zr10_25")
    assert center.snapshot()["devices"][0]["stopped_by_operator"]


def test_mode_switch_pauses_and_config_only_stopped(center, tmp_path):
    begin(center)
    assert not center.command({"action": "config", "config": center.cfg.to_dict()})["ok"]
    send(center, "mode", mode="scan")
    assert center.snapshot()["status"] == "paused"
    assert center.snapshot()["mode"] == "scan"
    send(center, "stop")
    changed = center.cfg.to_dict()
    changed["devices"][0]["position_m"] = [1, 2, 3]
    send(center, "config", config=changed)
    saved = send(center, "save_config", path=str(tmp_path/"edited.yaml"))
    assert load_config(saved["path"]).devices[0].position_m == [1, 2, 3]
    assert not center.command({"action": "save_config", "path": str(tmp_path/"bad.py")})["ok"]


def test_simulated_preview_is_opt_in_and_valid_jpeg(center):
    import cv2
    import numpy as np
    assert center.frame("zr10_25") is None
    send(center, "video", enabled=True)
    frame = center.frame("zr10_25")
    assert frame[:2] == b"\xff\xd8"
    assert cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), cv2.IMREAD_COLOR).shape == (360, 640, 3)
    assert center.frame("zr10_25") == frame
    send(center, "video", enabled=False)
    assert center.frame("zr10_25") is None


class FakeUnit:
    def __init__(self, device, cfg, sink):
        self.device, self.cfg, self.sink = device, cfg, sink
        self.online = True
        self.received = []
        self.stops = []
        self.latest_action = None

    def _check_action(self, action, now):
        return ActionValidator(self.cfg).validate(action, self.snapshot(), now, .1)

    def snapshot(self):
        return Telemetry(self.device.id, time.monotonic(), 0, 15, zoom=1, connected=self.online,
                         source="fake", raw={"zoom_known": False})

    def submit(self, action):
        self.latest_action = action
        self.received.append(action)
        self.sink(CommandResult(self.device.id, time.monotonic(), action, "sent_unconfirmed", True, False))

    def start(self):
        self.online = True

    async def cancel_pending(self, reason):
        self.latest_action = None
        self.stops.append(reason)

    async def close(self):
        await self.cancel_pending("close")
        self.online = False


class FakeFleet:
    instances = []
    def __init__(self, cfg, event_sink=None, result_sink=None, telemetry_sink=None):
        self.devices = {d.id: FakeUnit(d, cfg, result_sink) for d in cfg.active_devices}
        self.instances.append(self)

    async def start(self):
        pass

    def states(self):
        return {key: device.snapshot() for key, device in self.devices.items()}

    def history(self, key):
        return (self.devices[key].snapshot(),)

    def submit(self, actions):
        for key, action in actions.items():
            self.devices[key].submit(action)

    async def close(self):
        await asyncio.gather(*(device.close() for device in self.devices.values()))


def test_hardware_manual_without_yolo_or_site_calibration(monkeypatch, tmp_path):
    import zr10lab.hardware
    import zr10lab.vision
    monkeypatch.setattr(zr10lab.hardware, "HardwareFleet", FakeFleet)
    def forbidden(*args, **kwargs):
        raise AssertionError("手动、视频关闭时不能加载检测器或采集视频")
    monkeypatch.setattr(zr10lab.vision, "VisionPipeline", forbidden)
    c = ControlCenter(configuration(), output=tmp_path)
    try:
        begin(c, environment="hardware", armed=True)
        assert c.snapshot()["devices"][0]["feedback"]["zoom"] is None
        assert not c.command({"action": "mode", "mode": "scan"})["ok"]
        send(c, "manual", device_id="zr10_25", yaw_deg=5)
        wait_for(c, lambda s: s["devices"][0]["command"] is not None and s["devices"][0]["command"]["action"]["yaw_deg"] == 5)
        fleet = FakeFleet.instances[-1]
        send(c, "estop")
        count = len(fleet.devices["zr10_25"].received)
        time.sleep(.3)
        assert len(fleet.devices["zr10_25"].received) == count
        assert fleet.devices["zr10_25"].latest_action is None
    finally:
        c.close()


def test_non_idempotent_parameter_is_not_replayed(monkeypatch, tmp_path):
    import zr10lab.hardware
    monkeypatch.setattr(zr10lab.hardware, "HardwareFleet", FakeFleet)
    cfg = configuration()
    cfg.action_space["enabled"].append("photo")
    cfg.devices[0].capabilities["photo"] = True
    c = ControlCenter(cfg, output=tmp_path)
    try:
        begin(c, environment="hardware", armed=True)
        send(c, "manual", device_id="zr10_25", yaw_deg=5, parameters={"photo": True})
        time.sleep(.5)
        received = FakeFleet.instances[-1].devices["zr10_25"].received
        assert len([a for a in received if a.parameters.get("photo")]) == 1
        assert len([a for a in received if a.yaw_deg == 5]) >= 2
    finally:
        c.close()


def test_slow_policy_cannot_block_estop_or_apply_late_actions(monkeypatch, tmp_path):
    import zr10lab.control_modes
    entered, release = threading.Event(), threading.Event()
    class SlowPolicy:
        def reset(self):
            pass
        def decide(self, context):
            entered.set()
            release.wait(3)
            return Decision({"zr10_25": Action("zr10_25", yaw_deg=80, issued_t=context.t)})
    monkeypatch.setattr(zr10lab.control_modes, "create_mode_policy", lambda *a, **kw: SlowPolicy())
    c = ControlCenter(configuration(), output=tmp_path)
    try:
        begin(c)
        assert entered.wait(1)
        start = time.monotonic()
        send(c, "estop")
        assert time.monotonic()-start < .5
        release.set()
        time.sleep(.2)
        assert c.snapshot()["devices"][0]["feedback"]["yaw_deg"] == 0
        assert c.snapshot()["status"] == "estopped"
    finally:
        release.set()
        c.close()


def test_preview_read_does_not_consume_fusion_detection_batches():
    import numpy as np
    from zr10lab.vision import VisionPipeline, VideoFrame, DetectionBatch, PixelDetection
    cfg = configuration()
    pipeline = VisionPipeline(cfg, sources={}, detection_enabled=False)
    now = time.monotonic()
    frame = VideoFrame("zr10_25", 1, np.zeros((10, 10, 3), dtype=np.uint8), now, now, time.time())
    batch = DetectionBatch(frame, (PixelDetection((1,1,5,5), .9),), now, now)
    pipeline._batches["zr10_25"] = batch
    pipeline._preview["zr10_25"] = batch
    assert pipeline.preview_batch("zr10_25") is batch
    assert pipeline.preview_batch("zr10_25") is batch
    assert len(pipeline.collect()) == 1
    assert len(pipeline.collect()) == 0
    assert pipeline.preview_batch("zr10_25") is batch


def test_invalid_mode_configuration_is_atomic(center):
    old = center.snapshot()["config"]
    bad = center.cfg.to_dict()
    bad["control_center"]["modes"] = [{"id": "broken"}]
    assert not center.command({"action": "config", "config": bad})["ok"]
    assert center.snapshot()["config"] == old
    assert center.snapshot()["status"] == "idle"


def test_failed_detection_mode_keeps_old_policy_paused(monkeypatch, tmp_path):
    import zr10lab.hardware
    import zr10lab.vision
    monkeypatch.setattr(zr10lab.hardware, "HardwareFleet", FakeFleet)
    cfg = configuration()
    def missing(*args, **kwargs):
        raise FileNotFoundError("test missing weights")
    monkeypatch.setattr(zr10lab.vision, "VisionPipeline", missing)
    c = ControlCenter(cfg, output=tmp_path)
    try:
        begin(c, environment="hardware", armed=True)
        result = c.command({"action": "mode", "mode": "track"})
        assert not result["ok"]
        assert c.snapshot()["mode"] == "manual"
        assert c.snapshot()["status"] == "paused"
    finally:
        c.close()


def test_stop_during_model_load_does_not_start_capture(monkeypatch):
    import zr10lab.vision as vision
    entered, released = threading.Event(), threading.Event()
    class Source:
        started = False
        def start(self):
            self.started = True
        def close(self):
            pass
    source = Source()
    def load(_):
        entered.set()
        released.wait(2)
        return object()
    monkeypatch.setattr(vision, "create_detector", load)
    pipeline = vision.VisionPipeline(configuration(), sources={"zr10_25": source})
    async def scenario():
        task = asyncio.create_task(pipeline.start())
        while not entered.is_set():
            await asyncio.sleep(.01)
        pipeline.request_stop()
        released.set()
        await task
        await pipeline.close()
    asyncio.run(scenario())
    assert not source.started


def test_restart_uses_changed_plugin_source_in_same_process(tmp_path, monkeypatch):
    module_name = "zr10_restart_policy_fixture"
    module = tmp_path / f"{module_name}.py"
    source = ("from zr10lab.models import Decision\n"
              "class Demo:\n"
              "    def __init__(self, cfg): self.cfg = cfg\n"
              "    def reset(self): pass\n"
              "    def decide(self, context): return Decision({}, {'version': 1})\n")
    module.write_text(source, encoding="utf-8")
    original_stat = module.stat()
    monkeypatch.syspath_prepend(str(tmp_path))
    cfg = configuration()
    cfg.policy.update(name="custom", custom=f"{module_name}:Demo")
    c = ControlCenter(cfg, output=tmp_path / "runs")
    try:
        begin(c, mode="custom")
        first = wait_for(c, lambda s: s["diagnostics"].get("policy", {}).get("version") == 1)
        send(c, "stop")
        module.write_text(source.replace("'version': 1", "'version': 2"), encoding="utf-8")
        # 强制同时间戳和相同大小，验证并非碰巧绕过了Python字节码缓存。
        os.utime(module, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        begin(c, mode="custom")
        second = wait_for(c, lambda s: s["diagnostics"].get("policy", {}).get("version") == 2)
        assert second["session_path"] != first["session_path"]
        send(c, "stop")
        module.write_text("syntax invalid here !!!\n", encoding="utf-8")
        send(c, "heartbeat")
        send(c, "start", mode="custom", duration_s=0)
        failed = wait_for(c, lambda s: s["status"] == "error")
        assert "SyntaxError" in failed["error"]
        assert all(d["target"] is None for d in failed["devices"])
    finally:
        c.close()
        sys.modules.pop(module_name, None)


def test_applying_new_geometry_clears_old_derived_results(center):
    begin(center)
    wait_for(center, lambda s: bool(s["metrics"]))
    send(center, "stop")
    previous_path = center.snapshot()["session_path"]
    # 放入旧空间结果以验证配置提交清理，而非依赖随机仿真必须恰好出现轨迹。
    center._histories["old"] = [[1, 2, 3]]
    center._history_samples["old"] = [{"t": 1., "position_m": [1, 2, 3], "measured": False}]
    center._frames["zr10_25"] = (time.monotonic(), b"old-image")
    cfg = center.cfg.to_dict()
    cfg["devices"][0]["position_m"] = [7, 8, 9]
    send(center, "config", config=cfg)
    snap = center.snapshot()
    assert snap["tracks"] == [] and snap["detections"] == [] and snap["metrics"] == {}
    assert center._histories == {} and center._history_samples == {} and center._frames == {}
    assert snap["session_path"] == previous_path


def test_encoding_rejected_before_any_movement_or_camera_side_effect(monkeypatch, tmp_path):
    import zr10lab.hardware
    monkeypatch.setattr(zr10lab.hardware, "HardwareFleet", FakeFleet)
    cfg = configuration()
    cfg.action_space["enabled"] += ["photo", "encoding"]
    cfg.devices[0].capabilities.update(photo=True, encoding=True)
    c = ControlCenter(cfg, output=tmp_path)
    try:
        begin(c, environment="hardware", armed=True)
        unit = FakeFleet.instances[-1].devices["zr10_25"]
        stops_before = len(unit.stops)
        result = c.command({"action": "manual", "device_id": "zr10_25", "yaw_deg": 20,
                            "parameters": {"photo": True, "encoding": {"width": 1280, "height": 720, "bitrate_kbps": 3000}}})
        assert not result["ok"] and "停止实验" in result["error"]
        assert len(unit.stops) == stops_before
        assert not any(a.yaw_deg == 20 or a.parameters for a in unit.received)
        assert not c.snapshot()["devices"][0]["manual_override"]
    finally:
        c.close()


def test_history_samples_preserve_measurement_flags_and_are_bounded(tmp_path):
    c = ControlCenter(configuration(), output=tmp_path)
    for index in range(350):
        c._tracks = [Track("T1", float(index), (float(index), 2., 3.), (1., 0., 0.),
                           ((1.,0.,0.), (0.,1.,0.), (0.,0.,1.)), float(index), index+1,
                           "confirmed" if index % 2 else "coasting", measured=bool(index % 2))]
        c._remember_tracks()
    c._publish()
    track = c.snapshot()["tracks"][0]
    assert len(track["history"]) == len(track["history_samples"]) == 300
    assert track["history_samples"][0] == {"t": 50., "position_m": [50.,2.,3.], "measured": False}
    assert track["history_samples"][-1]["measured"] is True
    assert track["history"] == [sample["position_m"] for sample in track["history_samples"]]
    # 只读快照隔离：页面修改自己的JSON对象不会污染后台历史。
    track["history_samples"][0]["position_m"][0] = -1
    assert c.snapshot()["tracks"][0]["history_samples"][0]["position_m"][0] == 50.
    c._tracks = []
    c._remember_tracks()
    assert c._histories == {} and c._history_samples == {}
    c.close()
