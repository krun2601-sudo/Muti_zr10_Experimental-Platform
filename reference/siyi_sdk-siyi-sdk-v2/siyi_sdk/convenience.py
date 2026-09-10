# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Convenience factory functions for creating SIYI SDK clients.

This module provides easy-to-use factory functions for creating
SIYIClient instances with UDP, TCP, or Serial transports.
"""

from __future__ import annotations

from siyi_sdk.client import SIYIClient
from siyi_sdk.constants import DEFAULT_BAUD, DEFAULT_IP, DEFAULT_TCP_PORT, DEFAULT_UDP_PORT
from siyi_sdk.transport.serial import SerialTransport
from siyi_sdk.transport.tcp import TCPTransport
from siyi_sdk.transport.udp import UDPTransport


async def connect_udp(
    ip: str = DEFAULT_IP,
    port: int = DEFAULT_UDP_PORT,
    *,
    timeout: float = 2.0,
    max_retries: int = 2,
    auto_reconnect: bool = False,
) -> SIYIClient:
    """Create and connect a SIYI client using UDP transport.

    Args:
        ip: Gimbal IP address.
        port: UDP port.
        timeout: Default command timeout in seconds.
        max_retries: Maximum retry attempts for idempotent commands (0 = no retries).
        auto_reconnect: Enable automatic reconnection on failure.

    Returns:
        Connected SIYIClient instance.

    Raises:
        ConnectionError: If connection cannot be established.

    Example:
        >>> client = await connect_udp("192.168.144.25")
        >>> version = await client.get_firmware_version()
        >>> await client.close()
    """
    transport = UDPTransport(ip=ip, port=port)
    client = SIYIClient(transport, default_timeout=timeout, max_retries=max_retries, auto_reconnect=auto_reconnect)
    await client.connect()
    return client


async def connect_tcp(
    ip: str = DEFAULT_IP,
    port: int = DEFAULT_TCP_PORT,
    *,
    timeout: float = 2.0,
    max_retries: int = 2,
    auto_reconnect: bool = False,
) -> SIYIClient:
    """Create and connect a SIYI client using TCP transport.

    TCP transports automatically send heartbeat frames every 1 second.

    Args:
        ip: Gimbal IP address.
        port: TCP port.
        timeout: Default command timeout in seconds.
        max_retries: Maximum retry attempts for idempotent commands (0 = no retries).
        auto_reconnect: Enable automatic reconnection on failure.

    Returns:
        Connected SIYIClient instance.

    Raises:
        ConnectionError: If connection cannot be established.

    Example:
        >>> client = await connect_tcp("192.168.144.25")
        >>> version = await client.get_firmware_version()
        >>> await client.close()
    """
    transport = TCPTransport(ip=ip, port=port)
    client = SIYIClient(transport, default_timeout=timeout, max_retries=max_retries, auto_reconnect=auto_reconnect)
    await client.connect()
    return client


async def connect_serial(
    device: str,
    baud: int = DEFAULT_BAUD,
    *,
    timeout: float = 2.0,
    max_retries: int = 2,
    auto_reconnect: bool = False,
) -> SIYIClient:
    """Create and connect a SIYI client using Serial transport.

    Args:
        device: Serial device path (e.g., "/dev/ttyUSB0" or "COM3").
        baud: Baud rate.
        timeout: Default command timeout in seconds.
        max_retries: Maximum retry attempts for idempotent commands (0 = no retries).
        auto_reconnect: Enable automatic reconnection on failure.

    Returns:
        Connected SIYIClient instance.

    Raises:
        ConnectionError: If connection cannot be established.

    Example:
        >>> client = await connect_serial("/dev/ttyUSB0", 115200)
        >>> version = await client.get_firmware_version()
        >>> await client.close()
    """
    transport = SerialTransport(device=device, baud=baud)
    client = SIYIClient(transport, default_timeout=timeout, max_retries=max_retries, auto_reconnect=auto_reconnect)
    await client.connect()
    return client
