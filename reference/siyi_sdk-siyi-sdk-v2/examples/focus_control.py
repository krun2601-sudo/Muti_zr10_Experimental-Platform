# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Demonstrate auto focus and manual focus control."""

import asyncio

from siyi_sdk import configure_logging, connect_udp


async def main() -> None:
    """Trigger auto focus on center pixel, then do a brief manual focus sweep."""
    async with await connect_udp("192.168.144.25", 37260) as client:
        # auto focus centred on 1280x720 frame
        await client.auto_focus(touch_x=640, touch_y=360)
        print("auto focus triggered at (640, 360)")
        await asyncio.sleep(1)

        # manual focus towards far for 0.5 s
        await client.manual_focus(1)
        print("focusing far…")
        await asyncio.sleep(0.5)

        await client.manual_focus(0)
        print("focus stopped")

        # manual focus towards near for 0.5 s
        await client.manual_focus(-1)
        print("focusing near…")
        await asyncio.sleep(0.5)

        await client.manual_focus(0)
        print("focus stopped")

        # return to auto focus
        await client.auto_focus(touch_x=640, touch_y=360)
        print("auto focus re-triggered")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
