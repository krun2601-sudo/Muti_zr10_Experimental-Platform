from __future__ import annotations

import asyncio
import time
import unittest
from types import SimpleNamespace

from zr10_coop.config import DeviceConfig, SystemConfig
from zr10_coop.device import ZR10Device
from zr10_coop.types import AETarget


class FakeClient:
    def __init__(self, fail_ack: bool = False) -> None:
        self.fail_ack = fail_ack
        self.rotate_calls = []
        self.nowait_calls = []

    async def rotate(self, yaw: int, pitch: int) -> None:
        self.rotate_calls.append((yaw, pitch))
        if self.fail_ack:
            raise TimeoutError("fake ACK timeout")

    async def rotate_nowait(self, yaw: int, pitch: int) -> None:
        self.nowait_calls.append((yaw, pitch))

    async def get_gimbal_attitude(self):
        return SimpleNamespace(
            yaw_deg=0.0,
            pitch_deg=0.0,
            roll_deg=0.0,
            yaw_rate_dps=0.0,
            pitch_rate_dps=0.0,
            roll_rate_dps=0.0,
        )


class DeviceCommandTests(unittest.IsolatedAsyncioTestCase):
    def make_device(self, *, fail_ack: bool = False):
        cfg = DeviceConfig(
            id="g1",
            name="g1",
            ip="192.168.144.25",
            control_mode="velocity_p",
            velocity_use_ack=True,
            velocity_ack_fallback_nowait=True,
        )
        sys_cfg = SystemConfig(
            command_resend_interval_s=0.0,
            stop_command_repetitions=1,
            stop_command_interval_s=0.0,
        )
        device = ZR10Device(cfg, sys_cfg)
        device.client = FakeClient(fail_ack=fail_ack)
        device.connected = True
        device.initialized = True
        device._stream_active = True
        device._store_attitude(
            SimpleNamespace(
                yaw_deg=0.0,
                pitch_deg=0.0,
                roll_deg=0.0,
                yaw_rate_dps=0.0,
                pitch_rate_dps=0.0,
                roll_rate_dps=0.0,
            ),
            source="test",
        )
        return device

    async def test_velocity_command_uses_ack(self):
        device = self.make_device()
        result = await device.send_target(
            AETarget(azimuth_deg=10.0, elevation_deg=0.0),
            force=True,
        )
        self.assertEqual(result.status, "velocity_acknowledged")
        self.assertTrue(result.ack_received)
        self.assertEqual(len(device.client.rotate_calls), 1)
        self.assertEqual(device.client.nowait_calls, [])

    async def test_ack_timeout_falls_back_to_nowait(self):
        device = self.make_device(fail_ack=True)
        result = await device.send_target(
            AETarget(azimuth_deg=10.0, elevation_deg=0.0),
            force=True,
        )
        self.assertEqual(result.status, "velocity_fallback_nowait")
        self.assertTrue(result.fallback_used)
        self.assertEqual(len(device.client.rotate_calls), 1)
        self.assertEqual(len(device.client.nowait_calls), 1)

    async def test_on_target_sends_reliable_stop(self):
        device = self.make_device()
        result = await device.send_target(
            AETarget(azimuth_deg=0.0, elevation_deg=0.0),
            force=True,
        )
        self.assertEqual(result.status, "on_target_stop_ack")
        self.assertEqual(device.client.rotate_calls[-1], (0, 0))


if __name__ == "__main__":
    unittest.main()
