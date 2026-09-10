# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Take a photo, record a short video, then list all media on the camera."""

import asyncio

from siyi_sdk import MediaClient, MediaType, configure_logging, connect_udp
from siyi_sdk.models import CaptureFuncType, FunctionFeedback


async def main() -> None:
    """Capture a still photo, record a short video clip, then list stored media."""
    async with await connect_udp("192.168.144.25", 37260) as client:
        feedback_received: list[FunctionFeedback] = []

        def on_feedback(fb: FunctionFeedback) -> None:
            feedback_received.append(fb)
            print(f"  feedback: {fb.name}")

        unsub = client.on_function_feedback(on_feedback)

        # take a photo
        await client.capture(CaptureFuncType.PHOTO)
        await asyncio.sleep(1)  # allow feedback to arrive
        print("photo capture sent")

        # start recording
        await client.capture(CaptureFuncType.START_RECORD)
        await asyncio.sleep(3)  # record for 3 seconds
        print("recording started, waiting 3 s…")

        # stop recording (second START_RECORD toggles off)
        await client.capture(CaptureFuncType.START_RECORD)
        await asyncio.sleep(1)
        print("recording stopped")

        unsub()

    # Browse media via the camera's HTTP web server (independent of UDP client)
    async with MediaClient("192.168.144.25") as media:
        print("\n--- Photos ---")
        dirs = await media.list_directories(MediaType.IMAGES)
        for d in dirs:
            count = await media.get_media_count(MediaType.IMAGES, d.path)
            print(f"  {d.name}/  ({count} files)")
            files = await media.list_files(MediaType.IMAGES, d.path, start=0, count=5)
            for f in files:
                print(f"    {f.name}  →  {f.url}")

        print("\n--- Videos ---")
        dirs = await media.list_directories(MediaType.VIDEOS)
        for d in dirs:
            count = await media.get_media_count(MediaType.VIDEOS, d.path)
            print(f"  {d.name}/  ({count} files)")
            files = await media.list_files(MediaType.VIDEOS, d.path, start=0, count=5)
            for f in files:
                print(f"    {f.name}  →  {f.url}")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
