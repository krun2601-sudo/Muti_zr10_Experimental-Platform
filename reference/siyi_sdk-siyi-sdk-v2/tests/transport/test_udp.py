# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for UDPTransport."""

from __future__ import annotations

import asyncio

import pytest

from siyi_sdk.exceptions import NotConnectedError
from siyi_sdk.transport.udp import UDPTransport


class EchoDatagramProtocol(asyncio.DatagramProtocol):
    """Simple UDP echo protocol for testing."""

    def __init__(self) -> None:
        """Initialize the echo protocol."""
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Store transport when connection is made."""
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Echo received datagram back to sender."""
        if self.transport:
            self.transport.sendto(data, addr)


@pytest.fixture
async def udp_echo_server() -> tuple[str, int]:
    """Create a UDP echo server for testing."""
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        EchoDatagramProtocol,
        local_addr=("127.0.0.1", 0),
    )

    # Get the actual port that was bound
    sock = transport.get_extra_info("socket")
    _, port = sock.getsockname()

    yield "127.0.0.1", port

    transport.close()


@pytest.mark.asyncio
async def test_udp_connect(udp_echo_server: tuple[str, int]) -> None:
    """Test UDP transport can connect."""
    ip, port = udp_echo_server
    transport = UDPTransport(ip=ip, port=port)

    assert not transport.is_connected
    await transport.connect()
    assert transport.is_connected

    await transport.close()


@pytest.mark.asyncio
async def test_udp_close(udp_echo_server: tuple[str, int]) -> None:
    """Test UDP transport can close."""
    ip, port = udp_echo_server
    transport = UDPTransport(ip=ip, port=port)

    await transport.connect()
    assert transport.is_connected

    await transport.close()
    assert not transport.is_connected


@pytest.mark.asyncio
async def test_udp_send_before_connect_raises() -> None:
    """Test send before connect raises NotConnectedError."""
    transport = UDPTransport(ip="127.0.0.1", port=12345)

    with pytest.raises(NotConnectedError, match="before connect"):
        await transport.send(b"\x01\x02\x03")


@pytest.mark.asyncio
async def test_udp_round_trip(udp_echo_server: tuple[str, int]) -> None:
    """Test UDP transport can send and receive data."""
    ip, port = udp_echo_server
    transport = UDPTransport(ip=ip, port=port)

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
async def test_udp_multiple_datagrams(udp_echo_server: tuple[str, int]) -> None:
    """Test UDP transport can handle multiple datagrams."""
    ip, port = udp_echo_server
    transport = UDPTransport(ip=ip, port=port)

    await transport.connect()

    # Send multiple datagrams
    data1 = b"\x01\x02\x03"
    data2 = b"\x04\x05\x06"
    data3 = b"\x07\x08\x09"

    await transport.send(data1)
    await transport.send(data2)
    await transport.send(data3)

    # Receive all echoed datagrams
    received = []
    count = 0
    async for chunk in transport.stream():
        received.append(chunk)
        count += 1
        if count >= 3:
            break

    # Order may vary with UDP, but all should be present
    assert len(received) == 3
    assert data1 in received
    assert data2 in received
    assert data3 in received

    await transport.close()


@pytest.mark.asyncio
async def test_udp_supports_heartbeat_false() -> None:
    """Test UDP transport does not support heartbeat."""
    transport = UDPTransport()
    assert not transport.supports_heartbeat


@pytest.mark.asyncio
async def test_udp_with_bind_port(udp_echo_server: tuple[str, int]) -> None:
    """Test UDP transport can bind to a specific local port."""
    ip, port = udp_echo_server

    # Use ephemeral port (0) to let the OS assign one
    # We can't reliably reuse a closed port immediately
    transport = UDPTransport(ip=ip, port=port, bind_port=0)
    await transport.connect()

    # Send and receive data
    test_data = b"\xaa\xbb\xcc"
    await transport.send(test_data)

    received = None
    async for chunk in transport.stream():
        received = chunk
        break

    assert received == test_data

    await transport.close()


@pytest.mark.asyncio
async def test_udp_connection_failure() -> None:
    """Test connection failure handling."""
    from siyi_sdk.exceptions import ConnectionError as ConnError

    # Use an invalid address to trigger connection error
    transport = UDPTransport(ip="999.999.999.999", port=99999)

    with pytest.raises(ConnError):
        await transport.connect()


@pytest.mark.asyncio
async def test_udp_stream_empty_after_close(udp_echo_server: tuple[str, int]) -> None:
    """Test stream terminates after close."""
    ip, port = udp_echo_server
    transport = UDPTransport(ip=ip, port=port)

    await transport.connect()

    # Send one datagram
    await transport.send(b"\x01\x02\x03")

    # Receive it
    received = []
    async for chunk in transport.stream():
        received.append(chunk)
        await transport.close()  # Close after receiving one

    assert len(received) == 1


@pytest.mark.asyncio
async def test_udp_multiple_close_safe(udp_echo_server: tuple[str, int]) -> None:
    """Test calling close multiple times is safe."""
    ip, port = udp_echo_server
    transport = UDPTransport(ip=ip, port=port)

    await transport.connect()
    await transport.close()
    await transport.close()  # Should not raise

    assert not transport.is_connected


@pytest.mark.asyncio
async def test_udp_send_after_close_raises(udp_echo_server: tuple[str, int]) -> None:
    """Test send after close raises NotConnectedError."""
    ip, port = udp_echo_server
    transport = UDPTransport(ip=ip, port=port)

    await transport.connect()
    await transport.close()

    with pytest.raises(NotConnectedError, match="before connect"):
        await transport.send(b"\x01\x02\x03")
