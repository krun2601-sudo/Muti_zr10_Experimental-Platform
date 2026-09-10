# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Structured logging configuration for SIYI SDK."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable, Mapping, MutableMapping
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    pass


def hexdump_processor(
    logger: object,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> Mapping[str, Any]:
    """Convert payload_bytes to hex string representation.

    Args:
        logger: The wrapped logger object.
        method_name: The name of the called method.
        event_dict: The event dictionary to process.

    Returns:
        The modified event dictionary.

    """
    if "payload_bytes" in event_dict:
        payload_bytes: bytes = event_dict.pop("payload_bytes")
        event_dict["payload_hex"] = payload_bytes.hex(sep=" ")
    return event_dict


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.

    Args:
        name: The logger name, typically __name__.

    Returns:
        A bound structlog logger.

    """
    return structlog.get_logger(name)  # type: ignore[no-any-return]


def configure_logging(
    level: str | None = None,
    trace: bool | None = None,
    fmt: str | None = None,
) -> None:
    """Configure logging for the SIYI SDK.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to
            environment variable SIYI_LOG_LEVEL or INFO. Ignored if trace=True.
        trace: Enable protocol trace mode. Defaults to environment variable
            SIYI_PROTOCOL_TRACE == "1". When True, forces DEBUG level and
            installs hexdump_processor.
        fmt: Output format — "console" (default, human-readable) or "json".
            Overridden by SIYI_LOG_FORMAT environment variable.
            Use "json" for log aggregators or structured pipelines.

    Examples:
        Basic setup for scripts and examples::

            from siyi_sdk import configure_logging
            configure_logging()                      # INFO, human-readable
            configure_logging(level="WARNING")       # suppress INFO messages
            configure_logging(fmt="json")            # machine-readable JSON
            configure_logging(trace=True)            # DEBUG + hex payloads

    """
    # Determine trace mode
    if trace is None:
        trace = os.environ.get("SIYI_PROTOCOL_TRACE") == "1"

    # Determine log level
    if level is None:
        level = os.environ.get("SIYI_LOG_LEVEL", "INFO")

    # Trace mode overrides level to DEBUG
    if trace:
        level = "DEBUG"

    # Determine output format
    if fmt is None:
        fmt = os.environ.get("SIYI_LOG_FORMAT", "console")

    # Convert string level to logging level
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Build processor chain
    processors: list[
        Callable[[Any, str, MutableMapping[str, Any]], Mapping[str, Any] | str | bytes]
    ] = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="%H:%M:%S" if fmt == "console" else "iso", utc=False),
    ]

    if trace:
        processors.append(hexdump_processor)

    if fmt == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(
            structlog.dev.ConsoleRenderer(
                colors=sys.stderr.isatty(),
            )
        )

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add a stream handler
    handler = logging.StreamHandler()
    handler.setLevel(numeric_level)
    root_logger.addHandler(handler)
