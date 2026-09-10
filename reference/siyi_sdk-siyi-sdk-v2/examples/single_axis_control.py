# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Control each gimbal axis independently using single-axis attitude commands."""

import asyncio

from siyi_sdk import configure_logging, connect_udp


async def main() -> None:
    """Move yaw to 45°, then pitch to -30°, each independently, then centre."""
    async with await connect_udp("192.168.144.25", 37260) as client:
        att = await client.get_gimbal_attitude()
        print(f"initial  yaw={att.yaw_deg:.1f}°  pitch={att.pitch_deg:.1f}°  roll={att.roll_deg:.1f}°")

        # move only yaw, pitch stays as-is (axis=0 for yaw)
        ack = await client.set_single_axis(angle_deg=45.0, axis=0)
        print(f"yaw set to 45°  →  yaw={ack.yaw_deg:.1f}°  pitch={ack.pitch_deg:.1f}°")
        await asyncio.sleep(1.5)

        # move only pitch, yaw stays as-is (axis=1 for pitch)
        ack = await client.set_single_axis(angle_deg=-30.0, axis=1)
        print(f"pitch set to -30°  →  yaw={ack.yaw_deg:.1f}°  pitch={ack.pitch_deg:.1f}°")
        await asyncio.sleep(1.5)

        await client.one_key_centering()
        print("returned to centre")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
