# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Query the current gimbal mode and cycle through lock, follow, and FPV modes."""

import asyncio

from siyi_sdk import configure_logging, connect_udp
from siyi_sdk.models import CaptureFuncType


async def main() -> None:
    """Print current mode then switch lock → follow → FPV → lock."""
    async with await connect_udp("192.168.144.25", 37260) as client:
        mode = await client.get_gimbal_mode()
        print(f"current mode: {mode.name}")

        for func, label in (
            (CaptureFuncType.LOCK_MODE, "LOCK"),
            (CaptureFuncType.FOLLOW_MODE, "FOLLOW"),
            (CaptureFuncType.FPV_MODE, "FPV"),
            (CaptureFuncType.LOCK_MODE, "LOCK"),
        ):
            await client.capture(func)
            await asyncio.sleep(0.5)
            mode = await client.get_gimbal_mode()
            print(f"switched to {label} → reported mode: {mode.name}")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
