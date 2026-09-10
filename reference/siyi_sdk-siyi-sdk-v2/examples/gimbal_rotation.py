# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Rotate the gimbal continuously with speed control, then stop and centre."""

import asyncio

from siyi_sdk import configure_logging, connect_udp


async def main() -> None:
    """Pan right at half speed for 2 s, tilt down for 1 s, then centre."""
    async with await connect_udp("192.168.144.25", 37260) as client:
        # pan right (positive yaw) at speed 50 for 2 seconds
        await client.rotate(yaw=50, pitch=0)
        print("panning right at speed 50…")
        await asyncio.sleep(2)

        # stop
        await client.rotate(yaw=0, pitch=0)
        print("stopped")

        # tilt down (negative pitch) at speed 30 for 1 second
        await client.rotate(yaw=0, pitch=-30)
        print("tilting down at speed 30…")
        await asyncio.sleep(1)

        # stop
        await client.rotate(yaw=0, pitch=0)
        print("stopped")

        # return to centre
        await client.one_key_centering()
        print("returned to centre")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
