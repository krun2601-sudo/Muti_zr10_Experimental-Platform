# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Subscribe to attitude push stream at 10 Hz for 5 seconds."""

import asyncio

from siyi_sdk import configure_logging, connect_udp
from siyi_sdk.models import DataStreamFreq, GimbalDataType


async def main() -> None:
    """Subscribe to gimbal attitude stream and print for 5 seconds."""
    async with await connect_udp("192.168.144.25", 37260) as client:

        def on_att(att):
            # type: ignore
            """Print attitude data as it arrives."""
            print(f"yaw={att.yaw_deg:.1f} pitch={att.pitch_deg:.1f}")

        unsub = client.on_attitude(on_att)
        await client.request_gimbal_stream(GimbalDataType.ATTITUDE, DataStreamFreq.HZ10)

        await asyncio.sleep(5)

        unsub()
        await client.request_gimbal_stream(GimbalDataType.ATTITUDE, DataStreamFreq.OFF)
        print("stream closed")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
