# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Demonstrate manual zoom, absolute zoom, and zoom range query."""

import asyncio

from siyi_sdk import configure_logging, connect_udp
from siyi_sdk.exceptions import TimeoutError as SIYITimeoutError


async def main() -> None:
    """Query zoom range, zoom in manually, set absolute zoom, then reset to 1x."""
    async with await connect_udp("192.168.144.25", 37260) as client:
        zoom_range = await client.get_zoom_range()
        # Fixed-lens cameras (e.g. A8 mini) report 1.0x optical range but still
        # support digital zoom. Pick a demo target that works for both cases.
        optical_max = zoom_range.max_zoom
        demo_target = min(5.0, optical_max) if optical_max > 1.0 else 2.0
        print(f"optical zoom range: 1.0x – {optical_max:.1f}x  (demo target: {demo_target:.1f}x)")

        current = await client.get_current_zoom()
        print(f"current zoom: {current:.1f}x")

        # zoom in for 1 second, then stop
        mag = await client.manual_zoom(1)
        print(f"zoom-in started, magnification={mag:.1f}x")
        await asyncio.sleep(1)
        mag = await client.manual_zoom(0)
        print(f"zoom stopped, magnification={mag:.1f}x")

        # jump to demo_target (optical zoom for ZR/ZT series, digital for A8 mini)
        try:
            await client.absolute_zoom(demo_target)
            print(f"jumped to {demo_target:.1f}x")
            await asyncio.sleep(1)

            current = await client.get_current_zoom()
            print(f"current zoom after absolute set: {current:.1f}x")

            await client.absolute_zoom(1.0)
            print("reset to 1.0x")
        except SIYITimeoutError:
            print("absolute zoom not supported on this camera (0x0F timed out)")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
