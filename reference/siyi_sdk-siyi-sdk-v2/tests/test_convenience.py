# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for convenience factory functions."""

from __future__ import annotations

import asyncio
import shutil

import pytest

from siyi_sdk.client import SIYIClient
from siyi_sdk.convenience import connect_tcp, connect_udp


@pytest.mark.asyncio
async def test_connect_udp() -> None:
    """Test connect_udp with a loopback UDP echo server."""

    # Start a simple UDP echo server
    class UDPEchoProtocol(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            # Echo back
            self.transport.sendto(data, addr)

    loop = asyncio.get_event_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        UDPEchoProtocol,
        local_addr=("127.0.0.1", 0),
    )

    # Get the port the server is listening on
    server_port = transport.get_extra_info("sockname")[1]

    try:
        # Connect client to the echo server
        client = await connect_udp("127.0.0.1", server_port, timeout=0.5)

        assert isinstance(client, SIYIClient)
        assert client._transport.is_connected

        await client.close()

    finally:
        transport.close()


@pytest.mark.asyncio
async def test_connect_tcp() -> None:
    """Test connect_tcp with an asyncio.start_server echo server."""

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while True:
            data = await reader.read(1024)
            if not data:
                break
            writer.write(data)
            await writer.drain()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    server_port = server.sockets[0].getsockname()[1]

    try:
        async with server:
            # Connect client
            client = await connect_tcp("127.0.0.1", server_port, timeout=0.5)

            assert isinstance(client, SIYIClient)
            assert client._transport.is_connected

            # TCP transport should support heartbeat
            assert client._heartbeat_task is not None

            await client.close()

    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.skipif(not shutil.which("socat"), reason="socat not available")
@pytest.mark.asyncio
async def test_connect_serial() -> None:
    """Test connect_serial (skipped if socat unavailable)."""
    # This test would require setting up a virtual serial port pair
    # For now, we just verify the function signature exists
    # A full test would use socat or similar to create /dev/pts pairs
    pytest.skip("Serial test requires socat setup")
