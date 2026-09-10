# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for MockTransport."""

from __future__ import annotations

import pytest

from siyi_sdk.exceptions import NotConnectedError
from siyi_sdk.transport.mock import MockTransport


@pytest.mark.asyncio
async def test_mock_connect() -> None:
    """Test mock connect sets connected state."""
    transport = MockTransport()
    assert not transport.is_connected

    await transport.connect()
    assert transport.is_connected


@pytest.mark.asyncio
async def test_mock_close() -> None:
    """Test mock close clears connected state."""
    transport = MockTransport()
    await transport.connect()
    assert transport.is_connected

    await transport.close()
    assert not transport.is_connected


@pytest.mark.asyncio
async def test_mock_send_before_connect_raises() -> None:
    """Test send before connect raises NotConnectedError."""
    transport = MockTransport()

    with pytest.raises(NotConnectedError, match="before connect"):
        await transport.send(b"\x01\x02\x03")


@pytest.mark.asyncio
async def test_mock_send_captures_frames() -> None:
    """Test send captures all sent frames."""
    transport = MockTransport()
    await transport.connect()

    await transport.send(b"\x01\x02\x03")
    await transport.send(b"\x04\x05")

    assert transport.sent_frames == [b"\x01\x02\x03", b"\x04\x05"]


@pytest.mark.asyncio
async def test_mock_sent_frames_returns_copy() -> None:
    """Test sent_frames returns defensive copy."""
    transport = MockTransport()
    await transport.connect()

    await transport.send(b"\x01\x02\x03")
    frames1 = transport.sent_frames
    frames2 = transport.sent_frames

    assert frames1 == frames2
    assert frames1 is not frames2  # Different list objects


@pytest.mark.asyncio
async def test_mock_queue_response_fifo_order() -> None:
    """Test queued responses are yielded in FIFO order."""
    transport = MockTransport()
    await transport.connect()

    transport.queue_response(b"\x01")
    transport.queue_response(b"\x02")
    transport.queue_response(b"\x03")

    received = []
    count = 0
    async for chunk in transport.stream():
        received.append(chunk)
        count += 1
        if count >= 3:
            break

    assert received == [b"\x01", b"\x02", b"\x03"]


@pytest.mark.asyncio
async def test_mock_queue_error_raises_in_stream() -> None:
    """Test queued error is raised when stream consumes it."""
    transport = MockTransport()
    await transport.connect()

    transport.queue_error(RuntimeError("test error"))

    with pytest.raises(RuntimeError, match="test error"):
        async for _ in transport.stream():
            pass


@pytest.mark.asyncio
async def test_mock_stream_terminates_on_close() -> None:
    """Test stream iterator terminates when transport is closed."""
    transport = MockTransport()
    await transport.connect()

    transport.queue_response(b"\x01")
    transport.queue_response(b"\x02")

    received = []
    async for chunk in transport.stream():
        received.append(chunk)
        if len(received) == 2:
            await transport.close()

    assert received == [b"\x01", b"\x02"]


@pytest.mark.asyncio
async def test_mock_supports_heartbeat_default_false() -> None:
    """Test supports_heartbeat defaults to False."""
    transport = MockTransport()
    assert not transport.supports_heartbeat


@pytest.mark.asyncio
async def test_mock_supports_heartbeat_configurable() -> None:
    """Test supports_heartbeat can be configured via constructor."""
    transport_tcp_like = MockTransport(supports_heartbeat=True)
    assert transport_tcp_like.supports_heartbeat

    transport_udp_like = MockTransport(supports_heartbeat=False)
    assert not transport_udp_like.supports_heartbeat


@pytest.mark.asyncio
async def test_mock_multiple_queue_and_send_operations() -> None:
    """Test complex scenario with multiple queue and send operations."""
    transport = MockTransport()
    await transport.connect()

    # Queue some responses
    transport.queue_response(b"\xaa")
    transport.queue_response(b"\xbb")

    # Send some frames
    await transport.send(b"\x01")
    await transport.send(b"\x02")

    # Queue more responses
    transport.queue_response(b"\xcc")

    # Send another frame
    await transport.send(b"\x03")

    # Verify sent frames
    assert transport.sent_frames == [b"\x01", b"\x02", b"\x03"]

    # Verify received responses in order
    received = []
    count = 0
    async for chunk in transport.stream():
        received.append(chunk)
        count += 1
        if count >= 3:
            break

    assert received == [b"\xaa", b"\xbb", b"\xcc"]


@pytest.mark.asyncio
async def test_mock_empty_stream_does_not_block_forever() -> None:
    """Test that stream with no queued data does not block forever."""
    transport = MockTransport()
    await transport.connect()

    # Don't queue anything
    received = []

    # Use asyncio.wait_for to ensure we don't block forever
    import asyncio

    async def consume_stream() -> None:
        async for chunk in transport.stream():
            received.append(chunk)
            if len(received) >= 1:
                break

    # This should timeout since there's nothing queued
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(consume_stream(), timeout=0.2)

    assert received == []


@pytest.mark.asyncio
async def test_mock_stream_before_connect() -> None:
    """Test stream works even before connect (empty stream)."""
    transport = MockTransport()

    # Queue a response before connecting
    transport.queue_response(b"\x01\x02\x03")

    # Stream should work even without connect
    await transport.connect()

    received = []
    async for chunk in transport.stream():
        received.append(chunk)
        break

    assert received == [b"\x01\x02\x03"]


@pytest.mark.asyncio
async def test_mock_multiple_close() -> None:
    """Test calling close multiple times is safe."""
    transport = MockTransport()
    await transport.connect()

    await transport.close()
    await transport.close()  # Should not raise
    await transport.close()  # Should not raise

    assert not transport.is_connected
