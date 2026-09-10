# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Integration tests for concurrent command dispatch.

These tests verify that the client correctly handles:
- Multiple concurrent distinct commands
- Timeout handling
- Response routing
"""

from __future__ import annotations

import struct

import pytest

from siyi_sdk.client import SIYIClient
from siyi_sdk.constants import (
    CMD_REQUEST_FIRMWARE_VERSION,
    CMD_REQUEST_HARDWARE_ID,
)
from siyi_sdk.exceptions import TimeoutError
from siyi_sdk.models import FirmwareVersion, HardwareID
from siyi_sdk.protocol.frame import Frame
from siyi_sdk.transport.mock import MockTransport


class TestTimeoutHandling:
    """Test timeout handling for commands."""

    @pytest.mark.asyncio
    async def test_timeout_on_no_response(
        self,
        mock_transport: MockTransport,
    ) -> None:
        """Test that timeout occurs when no response is received."""
        client = SIYIClient(mock_transport, default_timeout=0.1)
        await client.connect()

        # Don't queue any response
        with pytest.raises(TimeoutError):
            await client.get_firmware_version()

        await client.close()

    @pytest.mark.asyncio
    async def test_client_functional_after_timeout(
        self,
        mock_transport: MockTransport,
    ) -> None:
        """Test client remains functional after a timeout."""
        client = SIYIClient(mock_transport, default_timeout=0.1)
        await client.connect()

        # First request times out
        with pytest.raises(TimeoutError):
            await client.get_firmware_version()

        # Queue a response for the second request
        mock_transport.queue_response(
            Frame(
                ctrl=1,
                seq=1,
                cmd_id=CMD_REQUEST_HARDWARE_ID,
                data=bytes(12),
            ).to_bytes()
        )

        # Second request should succeed
        hw = await client.get_hardware_id()
        assert isinstance(hw, HardwareID)

        await client.close()


class TestSequentialCommands:
    """Test sequential command dispatch."""

    @pytest.mark.asyncio
    async def test_sequential_commands_succeed(
        self,
        mock_transport: MockTransport,
    ) -> None:
        """Test that sequential commands succeed."""
        client = SIYIClient(mock_transport, default_timeout=0.5)
        await client.connect()

        # Queue first response, send first command
        mock_transport.queue_response(
            Frame(
                ctrl=1,
                seq=0,
                cmd_id=CMD_REQUEST_FIRMWARE_VERSION,
                data=struct.pack("<III", 1, 2, 3),
            ).to_bytes()
        )
        fw = await client.get_firmware_version()
        assert isinstance(fw, FirmwareVersion)

        # Queue second response, send second command
        mock_transport.queue_response(
            Frame(
                ctrl=1,
                seq=1,
                cmd_id=CMD_REQUEST_HARDWARE_ID,
                data=bytes(12),
            ).to_bytes()
        )
        hw = await client.get_hardware_id()
        assert isinstance(hw, HardwareID)

        await client.close()
