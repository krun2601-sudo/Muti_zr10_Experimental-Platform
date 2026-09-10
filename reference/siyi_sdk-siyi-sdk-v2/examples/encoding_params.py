# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Read encoding parameters for all streams and update the main stream to 720p."""

import asyncio

from siyi_sdk import configure_logging, connect_udp
from siyi_sdk.models import EncodingParams, StreamType


async def main() -> None:
    """Display encoding params for recording/main/sub streams, then set main to 720p."""
    async with await connect_udp("192.168.144.25", 37260) as client:
        for stream in (StreamType.RECORDING, StreamType.MAIN, StreamType.SUB):
            p = await client.get_encoding_params(stream)
            print(
                f"{stream.name:10s}  enc={p.enc_type.name}"
                f"  {p.resolution_w}x{p.resolution_h}"
                f"  {p.bitrate_kbps} kbps"
                f"  {p.frame_rate} fps"
            )

        # update main stream: keep existing codec, switch to 720p 4 Mbps 30 fps
        current = await client.get_encoding_params(StreamType.MAIN)
        new_params = EncodingParams(
            stream_type=StreamType.MAIN,
            enc_type=current.enc_type,   # preserve whatever codec the camera uses
            resolution_w=1280,
            resolution_h=720,
            bitrate_kbps=4000,
            frame_rate=30,
        )
        ok = await client.set_encoding_params(new_params)
        print(f"\nmain stream updated: {ok}")

        updated = await client.get_encoding_params(StreamType.MAIN)
        print(
            f"verified  {updated.resolution_w}x{updated.resolution_h}"
            f"  {updated.bitrate_kbps} kbps"
        )


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
