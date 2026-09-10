# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Protocol layer for SIYI SDK.

This subpackage provides low-level protocol handling:
- CRC-16/XMODEM checksum calculation
- Frame encoding/decoding
- Streaming frame parser
"""

from __future__ import annotations

from .crc import crc16, crc16_check
from .frame import Frame
from .parser import FrameParser

__all__ = [
    "Frame",
    "FrameParser",
    "crc16",
    "crc16_check",
]
