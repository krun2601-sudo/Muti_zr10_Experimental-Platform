# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for SerialTransport.

These tests require socat and pyserial-asyncio to be available.
If not available, tests will be skipped.
"""

from __future__ import annotations

import asyncio
import shutil

import pytest

# Check for serial_asyncio availability
pytest.importorskip("serial_asyncio", reason="pyserial-asyncio not installed")

from siyi_sdk.exceptions import NotConnectedError
from siyi_sdk.transport.serial import SerialTransport


def has_socat() -> bool:
    """Check if socat is available on the system."""
    return shutil.which("socat") is not None


@pytest.fixture
async def pty_pair() -> tuple[str, str]:
    """Create a socat pty pair for testing.

    Returns:
        Tuple of (master_pty, slave_pty) paths.
    """
    if not has_socat():
        pytest.skip("socat not available")

    # Create a pty pair using socat
    # We'll create two linked pseudo-terminals
    proc = await asyncio.create_subprocess_exec(
        "socat",
        "-d",
        "-d",
        "pty,raw,echo=0,link=/tmp/siyi_test_master",
        "pty,raw,echo=0,link=/tmp/siyi_test_slave",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Give socat time to create the ptys
    await asyncio.sleep(0.5)

    yield "/tmp/siyi_test_master", "/tmp/siyi_test_slave"

    # Clean up
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()


@pytest.mark.asyncio
@pytest.mark.skipif(not has_socat(), reason="socat not available")
async def test_serial_connect(pty_pair: tuple[str, str]) -> None:
    """Test serial transport can connect."""
    master, _ = pty_pair
    transport = SerialTransport(device=master, baud=115200)

    assert not transport.is_connected
    await transport.connect()
    assert transport.is_connected

    await transport.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not has_socat(), reason="socat not available")
async def test_serial_close(pty_pair: tuple[str, str]) -> None:
    """Test serial transport can close."""
    master, _ = pty_pair
    transport = SerialTransport(device=master, baud=115200)

    await transport.connect()
    assert transport.is_connected

    await transport.close()
    assert not transport.is_connected


@pytest.mark.asyncio
async def test_serial_send_before_connect_raises() -> None:
    """Test send before connect raises NotConnectedError."""
    transport = SerialTransport(device="/dev/null", baud=115200)

    with pytest.raises(NotConnectedError, match="before connect"):
        await transport.send(b"\x01\x02\x03")


@pytest.mark.asyncio
@pytest.mark.skipif(not has_socat(), reason="socat not available")
async def test_serial_round_trip(pty_pair: tuple[str, str]) -> None:
    """Test serial transport can send and receive data."""
    master, slave = pty_pair

    # Create two transports, one for each end
    transport1 = SerialTransport(device=master, baud=115200)
    transport2 = SerialTransport(device=slave, baud=115200)

    await transport1.connect()
    await transport2.connect()

    # Send data from transport1
    test_data = b"\x55\x66\x01\x02\x03\x04\x05"
    await transport1.send(test_data)

    # Receive on transport2
    received = None
    async for chunk in transport2.stream():
        received = chunk
        break

    assert received == test_data

    await transport1.close()
    await transport2.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not has_socat(), reason="socat not available")
async def test_serial_bidirectional(pty_pair: tuple[str, str]) -> None:
    """Test bidirectional serial communication."""
    master, slave = pty_pair

    transport1 = SerialTransport(device=master, baud=115200)
    transport2 = SerialTransport(device=slave, baud=115200)

    await transport1.connect()
    await transport2.connect()

    # Send from transport1 to transport2
    data1 = b"\x01\x02\x03"
    await transport1.send(data1)

    received1 = None
    async for chunk in transport2.stream():
        received1 = chunk
        break

    assert received1 == data1

    # Send from transport2 to transport1
    data2 = b"\x04\x05\x06"
    await transport2.send(data2)

    received2 = None
    async for chunk in transport1.stream():
        received2 = chunk
        break

    assert received2 == data2

    await transport1.close()
    await transport2.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not has_socat(), reason="socat not available")
async def test_serial_supports_heartbeat_false() -> None:
    """Test serial transport does not support heartbeat."""
    transport = SerialTransport(device="/dev/null", baud=115200)
    assert not transport.supports_heartbeat


@pytest.mark.asyncio
async def test_serial_connection_failure() -> None:
    """Test connection failure handling with invalid device."""
    from siyi_sdk.exceptions import ConnectionError as ConnError

    transport = SerialTransport(device="/dev/nonexistent_device_xyz", baud=115200)

    with pytest.raises(ConnError, match="Failed to open serial port"):
        await transport.connect()


@pytest.mark.asyncio
@pytest.mark.skipif(not has_socat(), reason="socat not available")
async def test_serial_multiple_sends(pty_pair: tuple[str, str]) -> None:
    """Test serial transport can handle multiple sends."""
    master, slave = pty_pair

    transport1 = SerialTransport(device=master, baud=115200)
    transport2 = SerialTransport(device=slave, baud=115200)

    await transport1.connect()
    await transport2.connect()

    # Send multiple messages
    data1 = b"\x01\x02\x03"
    data2 = b"\x04\x05\x06"
    data3 = b"\x07\x08\x09"

    await transport1.send(data1)
    await asyncio.sleep(0.05)  # Small delay between sends
    await transport1.send(data2)
    await asyncio.sleep(0.05)
    await transport1.send(data3)

    # Receive all data (may come in chunks)
    received = b""
    expected = data1 + data2 + data3
    count = 0
    async for chunk in transport2.stream():
        received += chunk
        count += 1
        if len(received) >= len(expected) or count > 10:
            break

    assert received == expected

    await transport1.close()
    await transport2.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not has_socat(), reason="socat not available")
async def test_serial_custom_baud_rate(pty_pair: tuple[str, str]) -> None:
    """Test serial transport with custom baud rate."""
    master, slave = pty_pair

    # Use a different baud rate
    transport1 = SerialTransport(device=master, baud=9600)
    transport2 = SerialTransport(device=slave, baud=9600)

    await transport1.connect()
    await transport2.connect()

    # Send and receive data
    test_data = b"\xaa\xbb\xcc"
    await transport1.send(test_data)

    received = None
    async for chunk in transport2.stream():
        received = chunk
        break

    assert received == test_data

    await transport1.close()
    await transport2.close()
