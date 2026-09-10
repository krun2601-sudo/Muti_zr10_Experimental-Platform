# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Exception hierarchy for the SIYI SDK.

This module defines all custom exceptions used throughout the SDK,
organized in a hierarchical structure for granular error handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ProductID


# =============================================================================
# Base Exception
# =============================================================================


class SIYIError(Exception):
    """Base exception for all SIYI SDK errors."""

    pass


# =============================================================================
# Protocol Errors
# =============================================================================


class ProtocolError(SIYIError):
    """Base exception for protocol-level errors."""

    pass


class FramingError(ProtocolError):
    """Error in frame structure (bad STX, truncation, etc.)."""

    pass


@dataclass
class CRCError(ProtocolError):
    """CRC checksum mismatch.

    Attributes:
        expected: Expected CRC value.
        actual: Actual computed CRC value.
        frame_hex: Hex representation of the frame bytes.

    """

    expected: int
    actual: int
    frame_hex: str

    def __str__(self) -> str:
        """Return human-readable error message."""
        return (
            f"CRC mismatch: expected=0x{self.expected:04X} "
            f"actual=0x{self.actual:04X} frame={self.frame_hex}"
        )


@dataclass
class UnknownCommandError(ProtocolError):
    """Unknown command ID received.

    Attributes:
        cmd_id: The unrecognized command ID.

    """

    cmd_id: int

    def __str__(self) -> str:
        """Return human-readable error message."""
        return f"Unknown command ID: 0x{self.cmd_id:02X}"


@dataclass
class MalformedPayloadError(ProtocolError):
    """Payload does not match expected format.

    Attributes:
        cmd_id: Command ID of the malformed payload.
        reason: Description of what was wrong.

    """

    cmd_id: int
    reason: str

    def __str__(self) -> str:
        """Return human-readable error message."""
        return f"Malformed payload for command 0x{self.cmd_id:02X}: {self.reason}"


# =============================================================================
# Transport Errors
# =============================================================================


class TransportError(SIYIError):
    """Base exception for transport-level errors."""

    pass


class ConnectionError(TransportError):
    """Error establishing or maintaining connection."""

    pass


@dataclass
class TimeoutError(TransportError):
    """Command timed out waiting for response.

    Attributes:
        cmd_id: Command ID that timed out.
        timeout_s: Timeout duration in seconds.

    """

    cmd_id: int
    timeout_s: float

    def __str__(self) -> str:
        """Return human-readable error message."""
        return (
            f"Timeout waiting for response to command 0x{self.cmd_id:02X} "
            f"after {self.timeout_s:.1f}s"
        )


class SendError(TransportError):
    """Error sending data to device."""

    pass


class NotConnectedError(TransportError):
    """Operation attempted without active connection."""

    pass


# =============================================================================
# Command Errors
# =============================================================================


class CommandError(SIYIError):
    """Base exception for command-level errors."""

    pass


@dataclass
class NACKError(CommandError):
    """Device sent a negative acknowledgment.

    Attributes:
        cmd_id: Command ID that was rejected.
        error_code: Error code from the device.
        message: Human-readable error message.

    """

    cmd_id: int
    error_code: int
    message: str

    def __str__(self) -> str:
        """Return human-readable error message."""
        return (
            f"NACK for command 0x{self.cmd_id:02X}: error_code={self.error_code} ({self.message})"
        )


@dataclass
class ResponseError(CommandError):
    """Command response indicates failure.

    Attributes:
        cmd_id: Command ID that failed.
        sta: Status code from the response.

    """

    cmd_id: int
    sta: int

    def __str__(self) -> str:
        """Return human-readable error message."""
        return f"Command 0x{self.cmd_id:02X} failed with status={self.sta}"


@dataclass
class UnsupportedByProductError(CommandError):
    """Command not supported by the connected product.

    Attributes:
        cmd_id: Command ID that is not supported.
        product: Product that does not support the command.

    """

    cmd_id: int
    product: ProductID

    def __str__(self) -> str:
        """Return human-readable error message."""
        return f"Command 0x{self.cmd_id:02X} is not supported by {self.product.name}"


# =============================================================================
# Configuration Errors
# =============================================================================


class ConfigurationError(SIYIError):
    """Error in SDK configuration."""

    pass
