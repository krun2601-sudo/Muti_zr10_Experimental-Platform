# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for siyi_sdk.exceptions module."""

from __future__ import annotations

from siyi_sdk import exceptions
from siyi_sdk.models import ProductID


class TestExceptionHierarchy:
    """Test exception class hierarchy."""

    def test_siyi_error_is_base(self):
        """SIYIError should be the base for all SDK exceptions."""
        assert issubclass(exceptions.ProtocolError, exceptions.SIYIError)
        assert issubclass(exceptions.TransportError, exceptions.SIYIError)
        assert issubclass(exceptions.CommandError, exceptions.SIYIError)
        assert issubclass(exceptions.ConfigurationError, exceptions.SIYIError)

    def test_protocol_error_subclasses(self):
        """Protocol error subclasses should inherit from ProtocolError."""
        assert issubclass(exceptions.FramingError, exceptions.ProtocolError)
        assert issubclass(exceptions.CRCError, exceptions.ProtocolError)
        assert issubclass(exceptions.UnknownCommandError, exceptions.ProtocolError)
        assert issubclass(exceptions.MalformedPayloadError, exceptions.ProtocolError)

    def test_transport_error_subclasses(self):
        """Transport error subclasses should inherit from TransportError."""
        assert issubclass(exceptions.ConnectionError, exceptions.TransportError)
        assert issubclass(exceptions.TimeoutError, exceptions.TransportError)
        assert issubclass(exceptions.SendError, exceptions.TransportError)
        assert issubclass(exceptions.NotConnectedError, exceptions.TransportError)

    def test_command_error_subclasses(self):
        """Command error subclasses should inherit from CommandError."""
        assert issubclass(exceptions.NACKError, exceptions.CommandError)
        assert issubclass(exceptions.ResponseError, exceptions.CommandError)
        assert issubclass(exceptions.UnsupportedByProductError, exceptions.CommandError)


class TestCRCError:
    """Test CRCError exception."""

    def test_isinstance_protocol_error(self):
        """CRCError should be an instance of ProtocolError."""
        error = exceptions.CRCError(expected=0x1234, actual=0x5678, frame_hex="55 66 01")
        assert isinstance(error, exceptions.ProtocolError)

    def test_isinstance_siyi_error(self):
        """CRCError should be an instance of SIYIError."""
        error = exceptions.CRCError(expected=0x1234, actual=0x5678, frame_hex="55 66 01")
        assert isinstance(error, exceptions.SIYIError)

    def test_str_contains_expected(self):
        """CRCError str should contain expected CRC."""
        error = exceptions.CRCError(expected=0x1234, actual=0x5678, frame_hex="55 66 01")
        assert "0x1234" in str(error)

    def test_str_contains_actual(self):
        """CRCError str should contain actual CRC."""
        error = exceptions.CRCError(expected=0x1234, actual=0x5678, frame_hex="55 66 01")
        assert "0x5678" in str(error)

    def test_str_contains_frame_hex(self):
        """CRCError str should contain frame hex."""
        error = exceptions.CRCError(expected=0x1234, actual=0x5678, frame_hex="55 66 01")
        assert "55 66 01" in str(error)

    def test_field_preservation(self):
        """CRCError fields should be preserved."""
        error = exceptions.CRCError(expected=0x1234, actual=0x5678, frame_hex="55 66 01")
        assert error.expected == 0x1234
        assert error.actual == 0x5678
        assert error.frame_hex == "55 66 01"


class TestTimeoutError:
    """Test TimeoutError exception."""

    def test_isinstance_transport_error(self):
        """TimeoutError should be an instance of TransportError."""
        error = exceptions.TimeoutError(cmd_id=0x01, timeout_s=1.0)
        assert isinstance(error, exceptions.TransportError)

    def test_isinstance_siyi_error(self):
        """TimeoutError should be an instance of SIYIError."""
        error = exceptions.TimeoutError(cmd_id=0x01, timeout_s=1.0)
        assert isinstance(error, exceptions.SIYIError)

    def test_str_contains_cmd_id(self):
        """TimeoutError str should contain command ID."""
        error = exceptions.TimeoutError(cmd_id=0x01, timeout_s=1.0)
        assert "0x01" in str(error)

    def test_str_contains_timeout(self):
        """TimeoutError str should contain timeout value."""
        error = exceptions.TimeoutError(cmd_id=0x01, timeout_s=1.5)
        assert "1.5" in str(error)

    def test_field_preservation(self):
        """TimeoutError fields should be preserved."""
        error = exceptions.TimeoutError(cmd_id=0x01, timeout_s=1.5)
        assert error.cmd_id == 0x01
        assert error.timeout_s == 1.5


class TestResponseError:
    """Test ResponseError exception."""

    def test_isinstance_command_error(self):
        """ResponseError should be an instance of CommandError."""
        error = exceptions.ResponseError(cmd_id=0x07, sta=0)
        assert isinstance(error, exceptions.CommandError)

    def test_isinstance_siyi_error(self):
        """ResponseError should be an instance of SIYIError."""
        error = exceptions.ResponseError(cmd_id=0x07, sta=0)
        assert isinstance(error, exceptions.SIYIError)

    def test_str_contains_cmd_id(self):
        """ResponseError str should contain command ID."""
        error = exceptions.ResponseError(cmd_id=0x07, sta=0)
        assert "0x07" in str(error)

    def test_str_contains_sta(self):
        """ResponseError str should contain status."""
        error = exceptions.ResponseError(cmd_id=0x07, sta=0)
        assert "0" in str(error)

    def test_field_preservation(self):
        """ResponseError fields should be preserved."""
        error = exceptions.ResponseError(cmd_id=0x07, sta=0)
        assert error.cmd_id == 0x07
        assert error.sta == 0


class TestUnknownCommandError:
    """Test UnknownCommandError exception."""

    def test_isinstance_protocol_error(self):
        """UnknownCommandError should be an instance of ProtocolError."""
        error = exceptions.UnknownCommandError(cmd_id=0xFF)
        assert isinstance(error, exceptions.ProtocolError)

    def test_str_contains_cmd_id(self):
        """UnknownCommandError str should contain command ID."""
        error = exceptions.UnknownCommandError(cmd_id=0xFF)
        assert "0xFF" in str(error)

    def test_field_preservation(self):
        """UnknownCommandError fields should be preserved."""
        error = exceptions.UnknownCommandError(cmd_id=0xFF)
        assert error.cmd_id == 0xFF


class TestMalformedPayloadError:
    """Test MalformedPayloadError exception."""

    def test_isinstance_protocol_error(self):
        """MalformedPayloadError should be an instance of ProtocolError."""
        error = exceptions.MalformedPayloadError(cmd_id=0x01, reason="too short")
        assert isinstance(error, exceptions.ProtocolError)

    def test_str_contains_cmd_id(self):
        """MalformedPayloadError str should contain command ID."""
        error = exceptions.MalformedPayloadError(cmd_id=0x01, reason="too short")
        assert "0x01" in str(error)

    def test_str_contains_reason(self):
        """MalformedPayloadError str should contain reason."""
        error = exceptions.MalformedPayloadError(cmd_id=0x01, reason="too short")
        assert "too short" in str(error)

    def test_field_preservation(self):
        """MalformedPayloadError fields should be preserved."""
        error = exceptions.MalformedPayloadError(cmd_id=0x01, reason="too short")
        assert error.cmd_id == 0x01
        assert error.reason == "too short"


class TestNACKError:
    """Test NACKError exception."""

    def test_isinstance_command_error(self):
        """NACKError should be an instance of CommandError."""
        error = exceptions.NACKError(cmd_id=0x01, error_code=1, message="failed")
        assert isinstance(error, exceptions.CommandError)

    def test_str_contains_all_fields(self):
        """NACKError str should contain all fields."""
        error = exceptions.NACKError(cmd_id=0x01, error_code=1, message="failed")
        assert "0x01" in str(error)
        assert "1" in str(error)
        assert "failed" in str(error)

    def test_field_preservation(self):
        """NACKError fields should be preserved."""
        error = exceptions.NACKError(cmd_id=0x01, error_code=1, message="failed")
        assert error.cmd_id == 0x01
        assert error.error_code == 1
        assert error.message == "failed"


class TestUnsupportedByProductError:
    """Test UnsupportedByProductError exception."""

    def test_isinstance_command_error(self):
        """UnsupportedByProductError should be an instance of CommandError."""
        error = exceptions.UnsupportedByProductError(cmd_id=0x15, product=ProductID.A2_MINI)
        assert isinstance(error, exceptions.CommandError)

    def test_str_contains_cmd_id(self):
        """UnsupportedByProductError str should contain command ID."""
        error = exceptions.UnsupportedByProductError(cmd_id=0x15, product=ProductID.A2_MINI)
        assert "0x15" in str(error)

    def test_str_contains_product_name(self):
        """UnsupportedByProductError str should contain product name."""
        error = exceptions.UnsupportedByProductError(cmd_id=0x15, product=ProductID.A2_MINI)
        assert "A2_MINI" in str(error)

    def test_field_preservation(self):
        """UnsupportedByProductError fields should be preserved."""
        error = exceptions.UnsupportedByProductError(cmd_id=0x15, product=ProductID.A2_MINI)
        assert error.cmd_id == 0x15
        assert error.product == ProductID.A2_MINI


class TestSimpleExceptions:
    """Test simple exception classes without dataclass fields."""

    def test_framing_error(self):
        """FramingError should be a ProtocolError."""
        error = exceptions.FramingError("bad frame")
        assert isinstance(error, exceptions.ProtocolError)
        assert "bad frame" in str(error)

    def test_connection_error(self):
        """ConnectionError should be a TransportError."""
        error = exceptions.ConnectionError("connection refused")
        assert isinstance(error, exceptions.TransportError)
        assert "connection refused" in str(error)

    def test_send_error(self):
        """SendError should be a TransportError."""
        error = exceptions.SendError("send failed")
        assert isinstance(error, exceptions.TransportError)
        assert "send failed" in str(error)

    def test_not_connected_error(self):
        """NotConnectedError should be a TransportError."""
        error = exceptions.NotConnectedError("not connected")
        assert isinstance(error, exceptions.TransportError)
        assert "not connected" in str(error)

    def test_configuration_error(self):
        """ConfigurationError should be a SIYIError."""
        error = exceptions.ConfigurationError("bad config")
        assert isinstance(error, exceptions.SIYIError)
        assert "bad config" in str(error)
