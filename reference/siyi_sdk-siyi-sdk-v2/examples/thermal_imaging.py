# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Explore thermal camera features: pseudo-color palette, spot / global temperature."""

import asyncio

from siyi_sdk import configure_logging, connect_udp
from siyi_sdk.models import PseudoColor, TempMeasureFlag


async def main() -> None:
    """Cycle a few pseudo-color palettes, then measure spot and global temperature."""
    async with await connect_udp("192.168.144.25", 37260) as client:
        current_color = await client.get_pseudo_color()
        print(f"current pseudo-color: {current_color.name}")

        for palette in (PseudoColor.IRONBOW, PseudoColor.RAINBOW, PseudoColor.WHITE_HOT):
            result = await client.set_pseudo_color(palette)
            print(f"set pseudo-color → {result.name}")
            await asyncio.sleep(0.5)

        # restore original
        await client.set_pseudo_color(current_color)
        print(f"restored pseudo-color: {current_color.name}")

        # spot temperature at centre of frame
        tp = await client.temp_at_point(640, 360, TempMeasureFlag.MEASURE_ONCE)
        print(f"spot temperature at ({tp.x},{tp.y}) = {tp.temperature_c:.2f}°C")

        # global (whole-frame) min/max temperature
        tg = await client.temp_global(TempMeasureFlag.MEASURE_ONCE)
        print(
            f"global temperature  max={tg.max_c:.2f}°C at ({tg.max_x},{tg.max_y})"
            f"  min={tg.min_c:.2f}°C at ({tg.min_x},{tg.min_y})"
        )

        gain = await client.get_thermal_gain()
        print(f"thermal gain: {gain.name}")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
