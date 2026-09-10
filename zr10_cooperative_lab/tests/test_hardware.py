"""只使用内存假设备验证通信语义与故障路径；绝不访问真实 IP。"""
import asyncio
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from zr10lab.actions import ActionValidator
from zr10lab.config import DeviceConfig, LabConfig
from zr10lab.hardware import HardwareDevice, HardwareFleet, normalize_pitch, proportional_speed
from zr10lab.models import Action, Telemetry


class FakeClient:
    def __init__(self, fail_motion=False, delay=0):
        self.calls = []
        self.fail_motion, self.delay = fail_motion, delay

    async def rotate(self, yaw, pitch):
        self.calls.append(("rotate", yaw, pitch))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_motion:
            raise TimeoutError("模拟 ACK 丢失")

    async def rotate_nowait(self, yaw, pitch):
        self.calls.append(("rotate_nowait", yaw, pitch))

    async def set_attitude(self, yaw, pitch):
        self.calls.append(("set_attitude", yaw, pitch))
        return SimpleNamespace(yaw_deg=0, pitch_deg=0, roll_deg=0)

    async def absolute_zoom(self, zoom):
        self.calls.append(("absolute_zoom", zoom))

    async def manual_focus(self, direction):
        self.calls.append(("manual_focus", direction))

    async def manual_zoom(self, direction):
        self.calls.append(("manual_zoom", direction))

    async def capture(self, function):
        self.calls.append(("capture", function))

    async def get_current_zoom(self):
        self.calls.append(("get_current_zoom",))
        return 2.5

    async def close(self):
        self.calls.append(("close",))


def controller(mode="velocity_p", **control):
    d = DeviceConfig("25", control={"mode": mode, "pitch_velocity_sign": -1, "minimum_speed": 0,
                                     "rate_hz": 100, "command_timeout_s": 0.01, **control},
                     capabilities={"photo": True, "encoding": True, "focus_direction": True, "zoom_direction": True})
    cfg = LabConfig([d], system={"telemetry_stale_s": 0.1, "stop_repetitions": 2},
                    action_space={"enabled": ["yaw_deg", "pitch_deg", "zoom", "photo", "encoding", "focus_direction", "zoom_direction"]})
    results = []
    unit = HardwareDevice(d, cfg, result_sink=results.append)
    unit.client = FakeClient()
    unit._validator = ActionValidator(cfg)
    unit.sdk_models = SimpleNamespace(CaptureFuncType=SimpleNamespace(PHOTO=0))
    unit.state = Telemetry("25", time.monotonic(), 0, 0)
    return unit, results


def test_speed_is_integer_protocol_value_with_independent_pitch_sign():
    async def check():
        unit, results = controller()
        action = Action("25", yaw_deg=10, pitch_deg=5, issued_t=time.monotonic())
        await unit._execute(unit._check_action(action, time.monotonic()))
        assert unit.client.calls == [("rotate", 20, -10)]
        assert all(type(x) is int for x in unit.client.calls[0][1:])
        assert results[-1].ack and results[-1].applied["pitch_speed"] == -10
    asyncio.run(check())


def test_expired_stale_and_invalid_whole_actions_do_not_move():
    unit, _ = controller()
    now = time.monotonic()
    for action in [Action("25", 10, issued_t=now - 1, ttl_s=0.1),
                   Action("25", 10, parameters={"unregistered": 1}, issued_t=now),
                   Action("25", 10, parameters={"encoding": {"width": 1920}}, issued_t=now)]:
        with pytest.raises(ValueError):
            unit._check_action(action, now)
    unit.state = replace(unit.state, t=now - 1)
    with pytest.raises(ValueError, match="遥测"):
        unit._check_action(Action("25", 10, issued_t=now), now)
    assert unit.client.calls == []


def test_position_ack_is_not_used_as_new_telemetry():
    async def check():
        unit, results = controller(mode="position", yaw_sign=-1, yaw_offset_deg=2)
        original = unit.state
        await unit._execute(Action("25", 10, 5, issued_t=time.monotonic()))
        assert unit.client.calls == [("set_attitude", -8, 5)]
        assert unit.state is original
        assert results[-1].applied["receipt_attitude"]["yaw_deg"] == 0
    asyncio.run(check())


def test_ack_failure_stop_falls_back_and_stops_focus_zoom():
    async def check():
        unit, _ = controller()
        unit.client = FakeClient(fail_motion=True)
        unit._focus_active = unit._zoom_active = True
        await unit.safe_stop("test")
        assert unit.client.calls.count(("rotate", 0, 0)) == 2
        assert unit.client.calls.count(("rotate_nowait", 0, 0)) == 2
        assert ("manual_focus", 0) in unit.client.calls
        assert ("manual_zoom", 0) in unit.client.calls
        assert not unit._focus_active and not unit._zoom_active
        assert not unit._stopped  # 没有 ACK，不能假称已确认停止。
    asyncio.run(check())


def test_watchdog_reliably_stops_after_action_lease_expires():
    async def check():
        unit, _ = controller()
        unit.latest_action = Action("25", 10, issued_t=time.monotonic(), ttl_s=0.025)
        task = asyncio.create_task(unit._control_loop())
        await asyncio.sleep(0.065)
        unit._closing = True
        await task
        assert any(call[0] == "rotate" and call[1] != 0 for call in unit.client.calls)
        assert unit.client.calls[-1] == ("rotate", 0, 0)
    asyncio.run(check())


def test_non_idempotent_photo_runs_once_per_action_and_has_no_ack():
    async def check():
        unit, results = controller()
        action = Action("25", parameters={"photo": True}, issued_t=time.monotonic())
        await unit._execute(action)
        await unit._execute(action)
        assert unit.client.calls.count(("capture", 0)) == 1
        assert not results[0].ack
    asyncio.run(check())


def test_slow_device_does_not_block_another_device():
    async def check():
        slow, _ = controller()
        fast, _ = controller()
        slow.client = FakeClient(delay=0.1)
        slow._timeout = 0.2
        start = time.monotonic()
        a = Action("25", 5, issued_t=start)
        pending = asyncio.create_task(slow._execute(a))
        await fast._execute(a)
        assert time.monotonic() - start < 0.05
        await pending
    asyncio.run(check())


def test_telemetry_preserves_raw_pitch_and_canonical_angles():
    unit, _ = controller(pitch_sign=-1, pitch_offset_deg=2)
    unit._attitude(SimpleNamespace(yaw_deg=3, pitch_deg=170, roll_deg=1, yaw_rate_dps=4,
                                  pitch_rate_dps=5, roll_rate_dps=6))
    assert unit.state.pitch_deg == 12
    assert unit.state.raw["pitch_deg"] == 170
    assert unit.state.raw["timestamp_kind"] == "host_receive_estimate"
    assert len(unit.samples) == 1


def test_newer_action_cannot_be_overwritten_by_old_policy_response():
    unit, _ = controller()
    now = time.monotonic()
    unit.submit(Action("25", 5, issued_t=now))
    unit.submit(Action("25", 10, issued_t=now - 0.1))
    assert unit.latest_action.yaw_deg == 5


def test_protocol_helpers_and_manual_zoom_limit():
    assert proportional_speed(1000, 2, 25, 5, 0.5) == 25
    assert proportional_speed(-0.1, 2, 25, 5, 0.5) == 0
    assert normalize_pitch(170, True) == -10
    assert normalize_pitch(170, False) == 170
    unit, _ = controller()
    now = time.monotonic()
    with pytest.raises(ValueError, match="变焦反馈"):
        unit._check_action(Action("25", parameters={"zoom_direction": 1}, issued_t=now), now)


def test_independent_watchdog_cancels_slow_ack_before_stop():
    class SlowMotion(FakeClient):
        async def rotate(self, yaw, pitch):
            self.calls.append(("rotate", yaw, pitch))
            if yaw or pitch:
                await asyncio.sleep(5)

    async def check():
        unit, _ = controller()
        unit._timeout = 2
        unit.client = SlowMotion()
        unit.latest_action = Action("25", 10, issued_t=time.monotonic(), ttl_s=.03)
        control_task = asyncio.create_task(unit._control_loop())
        watchdog_task = asyncio.create_task(unit._watchdog_loop())
        await asyncio.sleep(.075)
        assert ("rotate", 0, 0) in unit.client.calls
        unit._closing = True
        await asyncio.gather(control_task, watchdog_task)
    asyncio.run(check())


def test_new_angle_actions_do_not_extend_old_manual_focus_lease():
    async def check():
        unit, _ = controller()
        now = time.monotonic()
        await unit._execute(Action("25", parameters={"focus_direction": 1}, issued_t=now, ttl_s=.01))
        unit.latest_action = Action("25", 0, issued_t=now, ttl_s=.5)
        watchdog_task = asyncio.create_task(unit._watchdog_loop())
        await asyncio.sleep(.035)
        unit._closing = True
        await watchdog_task
        assert ("manual_focus", 0) in unit.client.calls
    asyncio.run(check())


def test_partial_connection_failure_stops_and_closes_created_transport():
    class BrokenInitialization(FakeClient):
        async def get_firmware_version(self):
            raise RuntimeError("查询阶段失败")

    async def check():
        unit, _ = controller()
        client = BrokenInitialization()
        unit.client = None

        async def connector(*args, **kwargs):
            assert kwargs["max_retries"] == 0 and kwargs["auto_reconnect"] is False
            return client

        unit.connector = connector
        unit.start()
        await asyncio.sleep(.025)
        await unit.close()
        assert ("rotate", 0, 0) in client.calls
        assert client.calls[-1] == ("close",)
        assert unit.client is None and not unit.snapshot().connected
    asyncio.run(check())


def test_sink_failure_never_prevents_stop_and_transport_close():
    async def check():
        unit, _ = controller()
        client = unit.client
        unit.event_sink = lambda *args: (_ for _ in ()).throw(OSError("磁盘故障"))
        await unit.close()
        assert client.calls[-1] == ("close",)
        assert ("rotate", 0, 0) in client.calls
        assert "磁盘故障" in unit.last_sink_error
    asyncio.run(check())


def test_zoom_feedback_requires_freshness_and_transition_completion():
    async def check():
        unit, _ = controller()
        await unit._execute(Action("25", zoom=3, issued_t=time.monotonic()))
        assert not unit.snapshot().raw["zoom_known"]
        assert not unit.snapshot().raw["zoom_stable"]
        await unit._read_zoom()  # Fake 回传 2.5，仍未达到 3。
        assert unit.snapshot().raw["zoom_known"]
        assert not unit.snapshot().raw["zoom_stable"]
        unit._zoom_pending_target = 2.5
        await unit._read_zoom()
        assert unit.snapshot().raw["zoom_stable"]
        unit._zoom_t -= 3
        assert not unit.snapshot().raw["zoom_known"]
    asyncio.run(check())


def test_lens_only_action_stops_previous_gimbal_velocity():
    async def check():
        unit, _ = controller()
        await unit._execute(Action("25", 10, 5, issued_t=time.monotonic()))
        await unit._execute(Action("25", zoom=2, issued_t=time.monotonic()))
        assert unit.client.calls[-2:] == [("rotate", 0, 0), ("absolute_zoom", 2.0)]
        assert unit._stopped
    asyncio.run(check())


def test_stream_and_subscriptions_are_cleared_before_transport_close():
    class StreamClient(FakeClient):
        async def request_gimbal_stream(self, data_type, frequency):
            self.calls.append(("stream", data_type, frequency))

    async def check():
        unit, _ = controller()
        unit.client = StreamClient()
        client = unit.client
        unit.sdk_models = SimpleNamespace(GimbalDataType=SimpleNamespace(ATTITUDE=1),
                                          DataStreamFreq=SimpleNamespace(OFF=0))
        unit._stream = True
        unsubscribed = []
        unit._unsubscribe = lambda: unsubscribed.append("attitude")
        unit._unsubscribe_function = lambda: unsubscribed.append("function")
        await unit.close()
        assert unsubscribed == ["attitude", "function"]
        assert client.calls[-2:] == [("stream", 1, 0), ("close",)]
    asyncio.run(check())


def test_encoding_fps_or_unsupported_resolution_rejected_before_motion():
    unit, _ = controller()
    now = time.monotonic()
    for encoding in [dict(width=1920, height=1080, bitrate_kbps=4096, fps=30),
                     dict(width=640, height=480, bitrate_kbps=4096)]:
        with pytest.raises(ValueError):
            unit._check_action(Action("25", 10, parameters={"encoding": encoding}, issued_t=now), now)
    assert unit.client.calls == []


def test_false_trigger_does_not_claim_a_command_or_ack():
    async def check():
        unit, results = controller()
        await unit._execute(Action("25", parameters={"photo": False}, issued_t=time.monotonic()))
        assert unit.client.calls == []
        assert not results[-1].sent and not results[-1].ack
    asyncio.run(check())


def test_submit_snapshots_mutable_parameter_dictionary():
    unit, _ = controller()
    values = {"photo": True}
    unit.submit(Action("25", parameters=values, issued_t=time.monotonic()))
    values["photo"] = False
    assert unit.latest_action.parameters["photo"] is True


def test_raw_telemetry_sink_receives_each_sample_once_not_every_snapshot():
    samples = []
    unit, _ = controller()
    fleet = HardwareFleet(unit.cfg, telemetry_sink=samples.append)
    device = fleet.devices["25"]
    packet = SimpleNamespace(yaw_deg=3, pitch_deg=170, roll_deg=1, yaw_rate_dps=4,
                             pitch_rate_dps=5, roll_rate_dps=6)
    device._attitude(packet, "stream")
    fleet.states()
    fleet.states()
    device._attitude(packet, "poll")
    assert len(samples) == 2
    assert [sample.sequence for sample in samples] == [1, 2]
    assert [sample.source for sample in samples] == ["stream", "poll"]
    assert samples[0].raw["pitch_deg"] == 170
    assert samples[0].pitch_deg == -10
    assert samples[0].t <= samples[1].t
    assert fleet.history("25") == tuple(samples)


def test_raw_telemetry_sink_failure_preserves_sample_and_does_not_block_stop():
    async def check():
        unit, _ = controller()
        client = unit.client
        unit.telemetry_sink = lambda sample: (_ for _ in ()).throw(OSError("原始姿态日志故障"))
        unit._attitude(SimpleNamespace(yaw_deg=0, pitch_deg=0, roll_deg=0,
                                      yaw_rate_dps=0, pitch_rate_dps=0, roll_rate_dps=0))
        assert len(unit.samples) == 1
        assert "原始姿态日志故障" in unit.last_sink_error
        await unit.close()
        assert ("rotate", 0, 0) in client.calls
        assert client.calls[-1] == ("close",)
    asyncio.run(check())
