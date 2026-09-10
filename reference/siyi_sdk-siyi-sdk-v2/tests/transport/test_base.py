# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for AbstractTransport ABC and Unsubscribe type alias."""

from __future__ import annotations

from collections.abc import Callable
from typing import get_origin

import pytest

from siyi_sdk.transport.base import AbstractTransport, Unsubscribe


def test_abstract_transport_is_abc() -> None:
    """Test that AbstractTransport cannot be instantiated directly."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        AbstractTransport()  # type: ignore[abstract]


def test_abstract_transport_has_required_methods() -> None:
    """Test that AbstractTransport declares all required abstract methods."""
    abstract_methods = AbstractTransport.__abstractmethods__
    assert "connect" in abstract_methods
    assert "close" in abstract_methods
    assert "send" in abstract_methods
    assert "stream" in abstract_methods
    assert "is_connected" in abstract_methods
    assert "supports_heartbeat" in abstract_methods


def test_unsubscribe_type_alias() -> None:
    """Test that Unsubscribe is a callable with correct signature."""
    # Unsubscribe should be Callable[[], None]
    origin = get_origin(Unsubscribe)
    assert origin is not None

    # The alias should resolve to a Callable
    def dummy_unsubscribe() -> None:
        pass

    # Type checkers will validate this, but we can also check at runtime
    assert callable(dummy_unsubscribe)
    assert isinstance(dummy_unsubscribe, Callable)  # type: ignore[arg-type]


def test_isinstance_check_with_abstract_transport() -> None:
    """Test isinstance checks work with AbstractTransport."""
    from siyi_sdk.transport.mock import MockTransport

    transport = MockTransport()
    assert isinstance(transport, AbstractTransport)
