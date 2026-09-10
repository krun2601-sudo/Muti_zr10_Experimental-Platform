# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Connect to a SIYI gimbal over UDP and read firmware + attitude."""

import asyncio

from siyi_sdk import configure_logging, connect_udp


async def main() -> None:
    """Connect and display firmware version and gimbal attitude."""
    async with await connect_udp("192.168.144.25", 37260) as client:
        fw = await client.get_firmware_version()
        print(f"Camera={fw.camera} Gimbal={fw.gimbal} Zoom={fw.zoom}")

        att = await client.get_gimbal_attitude()
        print(f"yaw={att.yaw_deg:.1f} pitch={att.pitch_deg:.1f} roll={att.roll_deg:.1f}")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
