# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Move the gimbal to target yaw and pitch, then return to centre."""

import asyncio

from siyi_sdk import configure_logging, connect_udp


async def main() -> None:
    """Move gimbal to yaw=30°, pitch=-45°, then centre after delay."""
    async with await connect_udp("192.168.144.25", 37260) as client:
        ack = await client.set_attitude(yaw_deg=30.0, pitch_deg=-45.0)
        print(f"moved to yaw={ack.yaw_deg} pitch={ack.pitch_deg}")

        await asyncio.sleep(2)

        await client.one_key_centering()
        print("returned to centre")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
