# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Soft-reboot the camera and/or gimbal module."""

import asyncio
import sys

from siyi_sdk import configure_logging, connect_udp
from siyi_sdk.exceptions import TimeoutError


async def main(reboot_camera: bool, reboot_gimbal: bool) -> None:
    """Send a soft-reboot command and report which modules were rebooted."""
    if not reboot_camera and not reboot_gimbal:
        print("nothing to reboot — pass --camera and/or --gimbal")
        return

    async with await connect_udp("192.168.144.25", 37260) as client:
        print(
            f"rebooting: {'camera ' if reboot_camera else ''}"
            f"{'gimbal' if reboot_gimbal else ''}".strip()
        )
        try:
            cam_ok, gimbal_ok = await client.soft_reboot(
                camera=reboot_camera, gimbal=reboot_gimbal
            )
            print(f"ack  camera={cam_ok}  gimbal={gimbal_ok}")
        except TimeoutError:
            # Device reboots before it can send an ACK — command was received.
            print("rebooting… (no ACK — device went offline as expected)")


if __name__ == "__main__":
    configure_logging(level="INFO")
    reboot_camera = "--camera" in sys.argv
    reboot_gimbal = "--gimbal" in sys.argv
    asyncio.run(main(reboot_camera, reboot_gimbal))
