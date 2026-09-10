# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Print a full system info snapshot: firmware, hardware ID, time, IPs, camera state."""

import asyncio

from siyi_sdk import configure_logging, connect_udp
from siyi_sdk.exceptions import TimeoutError
from siyi_sdk.models import FirmwareVersion


def _fmt_hw(raw: bytes) -> str:
    """Return hardware ID as ASCII serial if printable, else hex."""
    stripped = raw.rstrip(b"\x00")
    if stripped and all(0x20 <= b < 0x7F for b in stripped):
        return stripped.decode()
    return raw.hex()


async def main() -> None:
    """Fetch and display all available system information."""
    async with await connect_udp("192.168.144.25", 37260, max_retries=0) as client:
        fw = await client.get_firmware_version()
        cam_fw = FirmwareVersion.format_word(fw.camera)
        gimbal_fw = FirmwareVersion.format_word(fw.gimbal)
        zoom_fw = FirmwareVersion.format_word(fw.zoom)
        print(f"firmware  camera={cam_fw}  gimbal={gimbal_fw}  zoom={zoom_fw}")

        hw = await client.get_hardware_id()
        serial = _fmt_hw(hw.raw)
        try:
            camera_type = hw.product_id.label
        except ValueError:
            camera_type = f"unknown (0x{hw.raw[0:2].decode()})"
        print(f"camera type: {camera_type}  serial: {serial}")

        try:
            t = await client.get_system_time()
            print(f"system time  unix_usec={t.unix_usec}  boot_ms={t.boot_ms}")
        except TimeoutError:
            print("system time: not supported by this model")

        try:
            gi = await client.get_gimbal_system_info()
            print(f"gimbal system info  laser_state={gi.laser_state}")
        except TimeoutError:
            print("gimbal system info: not supported by this model")

        try:
            cam = await client.get_camera_system_info()
            print(
                f"camera system info  recording={cam.record_sta.name}"
                f"  mode={cam.gimbal_motion_mode.name}"
                f"  mount={cam.gimbal_mounting_dir.name}"
                f"  output={cam.video_hdmi_or_cvbs.name}"
            )
        except TimeoutError:
            print("camera system info: not supported by this model")

        try:
            ip_cfg = await client.get_ip_config()
            print(f"network  ip={ip_cfg.ip}  mask={ip_cfg.mask}  gateway={ip_cfg.gateway}")
        except TimeoutError:
            print("network config: not supported by this model")


if __name__ == "__main__":
    configure_logging(level="INFO")
    asyncio.run(main())
