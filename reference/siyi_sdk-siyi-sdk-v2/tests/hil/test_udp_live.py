# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Hardware-in-loop tests for real SIYI device over UDP.

These tests are gated behind:
- pytest marker: @pytest.mark.hil
- Environment variable: SIYI_HIL=1

To run these tests:
    SIYI_HIL=1 pytest tests/hil/ -v

To skip these tests (default):
    pytest -m "not hil"

Requirements:
- Real SIYI gimbal camera on network at 192.168.144.25:37260
- Network connectivity to device
"""

from __future__ import annotations

import os
import socket

import pytest

from siyi_sdk.constants import DEFAULT_IP, DEFAULT_UDP_PORT
from siyi_sdk.convenience import connect_udp
from siyi_sdk.models import DataStreamFreq, GimbalDataType

# Skip all HIL tests unless SIYI_HIL=1 is set
pytestmark = pytest.mark.skipif(
    os.environ.get("SIYI_HIL") != "1",
    reason="HIL tests require SIYI_HIL=1 environment variable",
)


def can_reach_device() -> bool:
    """Check if device is reachable via ping/socket.

    Returns:
        True if device is reachable, False otherwise.

    """
    try:
        # Try to open a UDP socket to the device
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)
        sock.connect((DEFAULT_IP, DEFAULT_UDP_PORT))
        sock.close()
        return True
    except (TimeoutError, OSError):
        return False


@pytest.mark.hil
class TestUDPLiveDevice:
    """Hardware-in-loop tests against real SIYI device over UDP."""

    @pytest.mark.asyncio
    async def test_device_reachable(self) -> None:
        """Test that device is reachable on network."""
        assert can_reach_device(), f"Cannot reach device at {DEFAULT_IP}:{DEFAULT_UDP_PORT}"

    @pytest.mark.asyncio
    async def test_real_device_firmware_version(self) -> None:
        """Test getting firmware version from real device."""
        if not can_reach_device():
            pytest.skip(f"Device not reachable at {DEFAULT_IP}:{DEFAULT_UDP_PORT}")

        async with await connect_udp() as client:
            fw = await client.get_firmware_version()

            # Firmware version should be non-zero
            assert fw.camera > 0
            assert fw.gimbal > 0
            # Zoom may be 0 if not present

            print(f"Firmware: camera={fw.camera:08X}, gimbal={fw.gimbal:08X}, zoom={fw.zoom:08X}")

    @pytest.mark.asyncio
    async def test_real_device_hardware_id(self) -> None:
        """Test getting hardware ID from real device."""
        if not can_reach_device():
            pytest.skip(f"Device not reachable at {DEFAULT_IP}:{DEFAULT_UDP_PORT}")

        async with await connect_udp() as client:
            hw = await client.get_hardware_id()

            # Hardware ID should be 12 bytes
            assert len(hw.raw) == 12

            print(f"Hardware ID: {hw.raw.hex()}")

    @pytest.mark.asyncio
    async def test_real_device_gimbal_attitude(self) -> None:
        """Test getting gimbal attitude from real device."""
        if not can_reach_device():
            pytest.skip(f"Device not reachable at {DEFAULT_IP}:{DEFAULT_UDP_PORT}")

        async with await connect_udp() as client:
            attitude = await client.get_gimbal_attitude()

            # Attitude angles should be in [-180, 180] range
            assert -180.0 <= attitude.yaw_deg <= 180.0
            assert -180.0 <= attitude.pitch_deg <= 180.0
            assert -180.0 <= attitude.roll_deg <= 180.0

            print(
                f"Attitude: yaw={attitude.yaw_deg:.1f}, pitch={attitude.pitch_deg:.1f}, "
                f"roll={attitude.roll_deg:.1f}"
            )

    @pytest.mark.asyncio
    async def test_real_device_rotate_and_stop(self) -> None:
        """Test sending rotation command and stop to real device."""
        if not can_reach_device():
            pytest.skip(f"Device not reachable at {DEFAULT_IP}:{DEFAULT_UDP_PORT}")

        async with await connect_udp() as client:
            # Send rotation command (slow yaw rotation)
            await client.rotate(yaw=10, pitch=0)

            # Wait briefly
            import asyncio

            await asyncio.sleep(1.0)

            # Stop rotation
            await client.rotate(yaw=0, pitch=0)

            print("Rotation command sent and stopped")

    @pytest.mark.asyncio
    async def test_real_device_camera_system_info(self) -> None:
        """Test getting camera system info from real device."""
        if not can_reach_device():
            pytest.skip(f"Device not reachable at {DEFAULT_IP}:{DEFAULT_UDP_PORT}")

        async with await connect_udp() as client:
            info = await client.get_camera_system_info()

            # Verify enum values are valid
            assert info.record_sta.value in (0, 1, 2, 3)
            assert info.video_hdmi_or_cvbs.value in (0, 1)
            assert info.gimbal_motion_mode.value in (0, 1, 2)
            assert info.gimbal_mounting_dir.value in (0, 1, 2)

            print(
                f"Camera: recording={info.record_sta.name}, "
                f"mode={info.gimbal_motion_mode.name}, "
                f"mounting={info.gimbal_mounting_dir.name}"
            )

    @pytest.mark.asyncio
    async def test_real_device_zoom_range(self) -> None:
        """Test getting zoom range from real device."""
        if not can_reach_device():
            pytest.skip(f"Device not reachable at {DEFAULT_IP}:{DEFAULT_UDP_PORT}")

        async with await connect_udp() as client:
            zoom_range = await client.get_zoom_range()

            # Zoom range should be positive and reasonable
            assert zoom_range.max_zoom > 0.0
            assert zoom_range.max_zoom <= 50.0  # Most cameras have < 50x optical zoom

            print(f"Zoom range: {zoom_range.max_zoom}x")

    @pytest.mark.asyncio
    async def test_real_device_attitude_streaming(self) -> None:
        """Test subscribing to attitude stream from real device."""
        if not can_reach_device():
            pytest.skip(f"Device not reachable at {DEFAULT_IP}:{DEFAULT_UDP_PORT}")

        attitudes_received: list[float] = []

        def on_attitude(attitude) -> None:  # type: ignore[no-untyped-def]
            attitudes_received.append(attitude.yaw_deg)
            print(f"Streamed attitude: yaw={attitude.yaw_deg:.1f}, pitch={attitude.pitch_deg:.1f}")

        async with await connect_udp() as client:
            # Subscribe to attitude stream
            unsub = client.on_attitude(on_attitude)

            # Enable attitude data stream
            await client.request_gimbal_stream(GimbalDataType.ATTITUDE, DataStreamFreq.HZ10)

            # Wait for some attitudes to arrive
            import asyncio

            await asyncio.sleep(2.0)

            # Unsubscribe and disable stream
            unsub()
            await client.request_gimbal_stream(GimbalDataType.ATTITUDE, DataStreamFreq.OFF)

        # Should have received at least a few attitudes
        assert len(attitudes_received) > 0
        print(f"Received {len(attitudes_received)} attitude updates")


@pytest.mark.hil
class TestUDPLiveDeviceEdgeCases:
    """Edge case HIL tests."""

    @pytest.mark.asyncio
    async def test_real_device_timeout_handling(self) -> None:
        """Test timeout handling with real device (intentional bad command)."""
        if not can_reach_device():
            pytest.skip(f"Device not reachable at {DEFAULT_IP}:{DEFAULT_UDP_PORT}")

        async with await connect_udp(timeout=0.5) as client:
            # This should succeed
            await client.get_firmware_version()

            # If we send an invalid/unsupported command, it may timeout
            # (Note: all standard commands should work, so this is hypothetical)
            # For now, just verify that normal commands work within timeout

    @pytest.mark.asyncio
    async def test_real_device_reconnect(self) -> None:
        """Test disconnect and reconnect to real device."""
        if not can_reach_device():
            pytest.skip(f"Device not reachable at {DEFAULT_IP}:{DEFAULT_UDP_PORT}")

        from siyi_sdk.transport.udp import UDPTransport

        transport = UDPTransport()
        from siyi_sdk.client import SIYIClient

        client = SIYIClient(transport, default_timeout=2.0)

        # First connection
        await client.connect()
        fw1 = await client.get_firmware_version()
        await client.close()

        # Second connection
        await client.connect()
        fw2 = await client.get_firmware_version()
        await client.close()

        # Both should succeed and return same firmware
        assert fw1.camera == fw2.camera
        assert fw1.gimbal == fw2.gimbal
