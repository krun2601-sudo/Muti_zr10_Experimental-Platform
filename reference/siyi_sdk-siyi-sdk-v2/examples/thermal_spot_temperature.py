# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Read spot temperature at pixel (640, 360) on thermal sensor."""

import asyncio

from siyi_sdk import configure_logging, connect_udp
from siyi_sdk.models import TempMeasureFlag


async def main() -> None:
    """Query spot temperature at given pixel coordinates."""
    async with await connect_udp("192.168.144.25", 37260) as client:
        tp = await client.temp_at_point(640, 360, TempMeasureFlag.MEASURE_ONCE)
        print(f"temperature at ({tp.x},{tp.y}) = {tp.temperature_c:.2f}°C")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
