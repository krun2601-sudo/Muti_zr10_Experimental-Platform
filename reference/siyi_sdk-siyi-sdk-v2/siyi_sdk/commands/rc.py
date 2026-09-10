# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""RC channels command encoders and decoders (0x23, 0x24).

This module implements encoding/decoding for RC channel commands.
Note: Command 0x23 is marked "Not in use" in the specification.
"""

from __future__ import annotations

import struct

# Re-export from attitude module for convenience
from siyi_sdk.commands.attitude import decode_fc_stream_ack, encode_fc_stream
from siyi_sdk.constants import CMD_SEND_RC_CHANNELS
from siyi_sdk.exceptions import ConfigurationError, MalformedPayloadError
from siyi_sdk.models import RCChannels


def encode_rc_channels(ch: RCChannels) -> bytes:
    """Encode RC channels send (0x23).

    Note: This command is marked "Not in use" in the specification.

    Args:
        ch: RCChannels dataclass with 18 channels.

    Returns:
        38-byte payload (18 x uint16 LE + uint8 chancount + uint8 rssi).

    Raises:
        ConfigurationError: If channel data is invalid.

    """
    if len(ch.chans) != 18:
        raise ConfigurationError(f"chans must have exactly 18 elements, got {len(ch.chans)}")
    if not 0 <= ch.chancount <= 255:
        raise ConfigurationError(f"chancount must be in [0,255], got {ch.chancount}")
    if not 0 <= ch.rssi <= 255:
        raise ConfigurationError(f"rssi must be in [0,255], got {ch.rssi}")

    # Pack 18 uint16 values + 2 uint8 values
    payload = struct.pack("<18HBB", *ch.chans, ch.chancount, ch.rssi)
    return payload


def decode_rc_channels(payload: bytes) -> RCChannels:
    """Decode RC channels data.

    Note: This is not a typical response decoder, as 0x23 does not have an ACK.
    This function is provided for completeness if RC channel data is received
    via a data stream.

    Args:
        payload: 38 bytes (18 x uint16 LE + uint8 chancount + uint8 rssi).

    Returns:
        RCChannels dataclass.

    Raises:
        MalformedPayloadError: If payload length is not 38 bytes.

    """
    if len(payload) != 38:
        raise MalformedPayloadError(
            cmd_id=CMD_SEND_RC_CHANNELS,
            reason=f"expected 38 bytes, got {len(payload)}",
        )
    values = struct.unpack("<18HBB", payload)
    chans = values[:18]
    chancount = values[18]
    rssi = values[19]
    return RCChannels(chans=chans, chancount=chancount, rssi=rssi)


__all__ = [
    "decode_fc_stream_ack",
    "decode_rc_channels",
    "encode_fc_stream",
    "encode_rc_channels",
]
