# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Enable laser ranging, poll distance for 5 seconds."""

import asyncio

from siyi_sdk import configure_logging, connect_udp


async def main() -> None:
    """Enable laser, poll distance every second for 5 seconds, then disable."""
    async with await connect_udp("192.168.144.25", 37260) as client:
        await client.set_laser_ranging_state(True)
        print("laser enabled")

        for i in range(5):
            d = await client.get_laser_distance()
            msg = (
                "out of range"
                if d.distance_m is None
                else f"{d.distance_m:.1f} m"
            )
            print(f"  [{i+1}] {msg}")
            await asyncio.sleep(1)

        await client.set_laser_ranging_state(False)
        print("laser disabled")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
