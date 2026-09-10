# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Full-flow integration tests covering complete command sequences.

These tests verify end-to-end behavior of the client against mocked
transport with realistic frame sequences.
"""

from __future__ import annotations

import asyncio

import pytest

from siyi_sdk.client import SIYIClient
from siyi_sdk.exceptions import TimeoutError
from siyi_sdk.models import FunctionFeedback, GimbalAttitude, LaserDistance
from siyi_sdk.transport.mock import MockTransport


class TestConnectDisconnectFlow:
    """Test connection lifecycle management."""

    @pytest.mark.asyncio
    async def test_connect_fw_attitude_rotate_disconnect(
        self,
        connected_client: SIYIClient,
        mock_transport: MockTransport,
        frame_firmware_version_ack: bytes,
        frame_gimbal_attitude_ack: bytes,
        frame_gimbal_rotation_ack: bytes,
    ) -> None:
        """Test full flow: connect -> firmware -> attitude -> rotate -> disconnect."""
        # Queue firmware version ACK
        mock_transport.queue_response(frame_firmware_version_ack)
        fw = await connected_client.get_firmware_version()
        assert fw.camera == 0x01020304
        assert fw.gimbal == 0x05060708
        assert fw.zoom == 0x090A0B0C

        # Queue attitude ACK
        mock_transport.queue_response(frame_gimbal_attitude_ack)
        attitude = await connected_client.get_gimbal_attitude()
        assert attitude.yaw_deg == 10.0
        assert attitude.pitch_deg == 20.0
        assert attitude.roll_deg == 30.0

        # Queue rotation ACK
        mock_transport.queue_response(frame_gimbal_rotation_ack)
        await connected_client.rotate(yaw=100, pitch=50)

        # Disconnect
        await connected_client.close()
        assert not mock_transport.is_connected

    @pytest.mark.asyncio
    async def test_context_manager_auto_disconnect(
        self,
        mock_transport: MockTransport,
    ) -> None:
        """Test that context manager automatically disconnects."""
        client = SIYIClient(mock_transport, default_timeout=0.5)
        async with client:
            assert mock_transport.is_connected

        assert not mock_transport.is_connected


class TestAttitudeStreaming:
    """Test stream subscription and push frame handling."""

    @pytest.mark.asyncio
    async def test_attitude_streaming_subscribe_unsubscribe(
        self,
        connected_client: SIYIClient,
        mock_transport: MockTransport,
        frame_gimbal_attitude_ack: bytes,
    ) -> None:
        """Test subscribing/unsubscribing from attitude stream."""
        attitudes_received: list[GimbalAttitude] = []

        def on_attitude(att: GimbalAttitude) -> None:
            attitudes_received.append(att)

        # Subscribe
        unsub = connected_client.on_attitude(on_attitude)

        # Queue 5 attitude push frames
        for _ in range(5):
            mock_transport.queue_response(frame_gimbal_attitude_ack)

        # Wait for background task to process
        await asyncio.sleep(0.2)

        assert len(attitudes_received) == 5
        for att in attitudes_received:
            assert att.yaw_deg == 10.0
            assert att.pitch_deg == 20.0

        # Unsubscribe
        unsub()

        # Queue another attitude frame - should NOT be received
        mock_transport.queue_response(frame_gimbal_attitude_ack)
        await asyncio.sleep(0.1)

        assert len(attitudes_received) == 5  # No new attitude


class TestErrorRecovery:
    """Test error handling and recovery scenarios."""

    @pytest.mark.asyncio
    async def test_timeout_on_no_response(
        self,
        connected_client: SIYIClient,
        mock_transport: MockTransport,
    ) -> None:
        """Test TimeoutError when no ACK received."""
        # Don't queue any response
        with pytest.raises(TimeoutError):
            await connected_client.get_firmware_version()


class TestStreamPushFrames:
    """Test handling of unsolicited push frames."""

    @pytest.mark.asyncio
    async def test_function_feedback_push_received(
        self,
        connected_client: SIYIClient,
        mock_transport: MockTransport,
        frame_function_feedback_push: bytes,
    ) -> None:
        """Test reception of function feedback push (0x0B)."""
        feedbacks_received: list[FunctionFeedback] = []

        def on_feedback(fb: FunctionFeedback) -> None:
            feedbacks_received.append(fb)

        # Subscribe to function feedback
        unsub = connected_client.on_function_feedback(on_feedback)

        # Queue push frame
        mock_transport.queue_response(frame_function_feedback_push)
        await asyncio.sleep(0.1)

        assert len(feedbacks_received) == 1
        assert feedbacks_received[0] == FunctionFeedback.PHOTO_OK

        unsub()

    @pytest.mark.asyncio
    async def test_laser_distance_push_received(
        self,
        connected_client: SIYIClient,
        mock_transport: MockTransport,
        frame_laser_distance_ack: bytes,
    ) -> None:
        """Test reception of laser distance push (0x15)."""
        distances_received: list[LaserDistance] = []

        def on_laser(ld: LaserDistance) -> None:
            distances_received.append(ld)

        unsub = connected_client.on_laser_distance(on_laser)

        # Queue laser push frame
        mock_transport.queue_response(frame_laser_distance_ack)
        await asyncio.sleep(0.1)

        assert len(distances_received) == 1
        assert distances_received[0].distance_m is not None

        unsub()


class TestCommandRetries:
    """Test retry logic for idempotent read commands."""

    @pytest.mark.asyncio
    async def test_idempotent_read_retries_on_timeout(
        self,
        mock_transport: MockTransport,
        frame_firmware_version_ack: bytes,
    ) -> None:
        """Test that idempotent reads retry on timeout."""
        client = SIYIClient(mock_transport, default_timeout=0.2, max_retries=2)
        await client.connect()

        # First attempt: no response (timeout)
        # Second attempt: no response (timeout)
        # Third attempt: valid ACK
        mock_transport.queue_response(frame_firmware_version_ack)

        fw = await client.get_firmware_version()
        assert fw.camera == 0x01020304

        await client.close()

    @pytest.mark.asyncio
    async def test_write_command_does_not_retry(
        self,
        mock_transport: MockTransport,
    ) -> None:
        """Test that write commands do NOT retry on timeout."""
        client = SIYIClient(mock_transport, default_timeout=0.2, max_retries=2)
        await client.connect()

        # Don't queue any response - should timeout without retry
        with pytest.raises(TimeoutError):
            await client.rotate(10, 20)

        # Only 1 request sent (no retries)
        sent = mock_transport.sent_frames
        assert len(sent) == 1

        await client.close()
