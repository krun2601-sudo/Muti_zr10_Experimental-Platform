# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Extended tests for AI commands."""

from siyi_sdk.commands.ai import (
    decode_ai_stream_status,
    encode_get_ai_stream_status,
)
from siyi_sdk.models import AIStreamStatus


class TestAIStreamStatus:
    def test_encode(self):
        assert encode_get_ai_stream_status() == b""

    def test_decode_all(self):
        for i in range(4):
            result = decode_ai_stream_status(bytes([i]))
            assert result == AIStreamStatus(i)
