# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for TCPTransport."""

from __future__ import annotations

import asyncio

import pytest

from siyi_sdk.exceptions import NotConnectedError
from siyi_sdk.transport.tcp import TCPTransport


async def tcp_echo_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Simple TCP echo server handler."""
    try:
        while True:
            data = await reader.read(4096)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.fixture
async def tcp_echo_server_fixture() -> tuple[str, int]:
    """Create a TCP echo server for testing."""
    server = await asyncio.start_server(tcp_echo_server, "127.0.0.1", 0)

    # Get the actual port that was bound
    addr = server.sockets[0].getsockname() if server.sockets else ("127.0.0.1", 0)
    ip, port = addr[0], addr[1]

    async with server:
        yield ip, port


@pytest.mark.asyncio
async def test_tcp_connect(tcp_echo_server_fixture: tuple[str, int]) -> None:
    """Test TCP transport can connect."""
    ip, port = tcp_echo_server_fixture
    transport = TCPTransport(ip=ip, port=port)

    assert not transport.is_connected
    await transport.connect()
    assert transport.is_connected

    await transport.close()


@pytest.mark.asyncio
async def test_tcp_close(tcp_echo_server_fixture: tuple[str, int]) -> None:
    """Test TCP transport can close."""
    ip, port = tcp_echo_server_fixture
    transport = TCPTransport(ip=ip, port=port)

    await transport.connect()
    assert transport.is_connected

    await transport.close()
    assert not transport.is_connected


@pytest.mark.asyncio
async def test_tcp_send_before_connect_raises() -> None:
    """Test send before connect raises NotConnectedError."""
    transport = TCPTransport(ip="127.0.0.1", port=12345)

    with pytest.raises(NotConnectedError, match="before connect"):
        await transport.send(b"\x01\x02\x03")


@pytest.mark.asyncio
async def test_tcp_round_trip(tcp_echo_server_fixture: tuple[str, int]) -> None:
    """Test TCP transport can send and receive data."""
    ip, port = tcp_echo_server_fixture
    transport = TCPTransport(ip=ip, port=port)

    await transport.connect()

    # Send data
    test_data = b"\x55\x66\x01\x02\x03\x04\x05"
    await transport.send(test_data)

    # Receive echoed data
    received = None
    async for chunk in transport.stream():
        received = chunk
        break

    assert received == test_data

    await transport.close()


@pytest.mark.asyncio
async def test_tcp_multiple_sends(tcp_echo_server_fixture: tuple[str, int]) -> None:
    """Test TCP transport can handle multiple sends."""
    ip, port = tcp_echo_server_fixture
    transport = TCPTransport(ip=ip, port=port)

    await transport.connect()

    # Send multiple messages
    data1 = b"\x01\x02\x03"
    data2 = b"\x04\x05\x06"
    data3 = b"\x07\x08\x09"

    await transport.send(data1)
    await transport.send(data2)
    await transport.send(data3)

    # Receive all echoed data (may come in chunks)
    received = b""
    expected = data1 + data2 + data3
    async for chunk in transport.stream():
        received += chunk
        if len(received) >= len(expected):
            break

    assert received == expected

    await transport.close()


@pytest.mark.asyncio
async def test_tcp_supports_heartbeat_true() -> None:
    """Test TCP transport supports heartbeat."""
    transport = TCPTransport()
    assert transport.supports_heartbeat


@pytest.mark.asyncio
async def test_tcp_connection_refused() -> None:
    """Test connection failure handling when port is not listening."""
    from siyi_sdk.exceptions import ConnectionError as ConnError

    # Use a port that's unlikely to be listening
    transport = TCPTransport(ip="127.0.0.1", port=54321)

    with pytest.raises(ConnError, match="Failed to connect"):
        await transport.connect()


@pytest.mark.asyncio
async def test_tcp_stream_eof_on_server_close(tcp_echo_server_fixture: tuple[str, int]) -> None:
    """Test stream handles EOF gracefully when server closes connection."""
    ip, port = tcp_echo_server_fixture
    transport = TCPTransport(ip=ip, port=port)

    await transport.connect()

    # Send a message
    await transport.send(b"\x01\x02\x03")

    # Receive echo
    received = []
    async for chunk in transport.stream():
        received.append(chunk)
        # After first chunk, close our side which will trigger server close
        await transport.close()

    assert len(received) >= 1
    assert not transport.is_connected


@pytest.mark.asyncio
async def test_tcp_large_data_transfer(tcp_echo_server_fixture: tuple[str, int]) -> None:
    """Test TCP transport can handle large data transfers."""
    ip, port = tcp_echo_server_fixture
    transport = TCPTransport(ip=ip, port=port)

    await transport.connect()

    # Send a large payload (larger than typical buffer size)
    large_data = b"\xaa" * 10000
    await transport.send(large_data)

    # Receive all echoed data
    received = b""
    async for chunk in transport.stream():
        received += chunk
        if len(received) >= len(large_data):
            break

    assert received == large_data

    await transport.close()


@pytest.mark.asyncio
async def test_tcp_send_after_close_raises(tcp_echo_server_fixture: tuple[str, int]) -> None:
    """Test send after close raises NotConnectedError."""
    ip, port = tcp_echo_server_fixture
    transport = TCPTransport(ip=ip, port=port)

    await transport.connect()
    await transport.close()

    with pytest.raises(NotConnectedError, match="before connect"):
        await transport.send(b"\x01\x02\x03")


@pytest.mark.asyncio
async def test_tcp_multiple_close_calls_safe(tcp_echo_server_fixture: tuple[str, int]) -> None:
    """Test that calling close multiple times is safe."""
    ip, port = tcp_echo_server_fixture
    transport = TCPTransport(ip=ip, port=port)

    await transport.connect()
    await transport.close()
    await transport.close()  # Should not raise
    await transport.close()  # Should not raise

    assert not transport.is_connected


@pytest.mark.asyncio
async def test_tcp_stream_before_data() -> None:
    """Test stream can be created before any data is sent."""
    import asyncio

    # Create a simple server that doesn't send anything
    async def silent_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await asyncio.sleep(0.1)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(silent_server, "127.0.0.1", 0)
    addr = server.sockets[0].getsockname() if server.sockets else ("127.0.0.1", 0)
    ip, port = addr[0], addr[1]

    async with server:
        transport = TCPTransport(ip=ip, port=port)
        await transport.connect()

        # Try to read from stream (should get EOF)
        received = []
        async for chunk in transport.stream():
            received.append(chunk)

        # Should receive nothing (EOF)
        assert received == []
        assert not transport.is_connected

        await transport.close()
