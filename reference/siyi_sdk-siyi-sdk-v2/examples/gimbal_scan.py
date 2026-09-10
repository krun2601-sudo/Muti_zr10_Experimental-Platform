# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Automated gimbal scan: sweep yaw across a range while holding a fixed pitch."""

import asyncio

from siyi_sdk import configure_logging, connect_udp
from siyi_sdk.models import GimbalMotionMode, CaptureFuncType


async def scan(client, yaw_start: float, yaw_end: float, pitch: float, steps: int = 5) -> None:
    """Move the gimbal in discrete steps from yaw_start to yaw_end at fixed pitch."""
    step_deg = (yaw_end - yaw_start) / max(steps - 1, 1)
    for i in range(steps):
        yaw = yaw_start + i * step_deg
        ack = await client.set_attitude(yaw_deg=yaw, pitch_deg=pitch)
        print(f"  step {i+1}/{steps}  yaw={ack.yaw_deg:.1f}°  pitch={ack.pitch_deg:.1f}°")
        await asyncio.sleep(1.5)


async def main() -> None:
    """Switch to lock mode, sweep yaw from -60° to +60° at -20° pitch, then centre."""
    async with await connect_udp("192.168.144.25", 37260) as client:
        # lock mode gives accurate absolute positioning
        await client.capture(CaptureFuncType.LOCK_MODE)
        await asyncio.sleep(0.3)
        mode = await client.get_gimbal_mode()
        print(f"gimbal mode: {mode.name}")

        print("scanning left to right…")
        await scan(client, yaw_start=-60.0, yaw_end=60.0, pitch=-20.0, steps=7)

        await client.one_key_centering()
        print("returned to centre")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
