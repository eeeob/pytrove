"""`data_tools._internal.factories`: adapting zero-argument factories."""

from __future__ import annotations as _annotations

import pytest

from pytrove.data_tools._internal import _no_arg_factory


def test_no_arg_factory_ignores_the_key_and_keeps_the_original() -> None:
    adapted = _no_arg_factory(list)

    assert adapted("any key") == []
    assert adapted.__wrapped__ is list  # type: ignore[attr-defined]  # Set by `ignore_arguments`.


def test_no_arg_factory_does_not_wrap_an_adapter_twice() -> None:
    once = _no_arg_factory(list)
    twice = _no_arg_factory(once)  # type: ignore[arg-type]  # Handing the adapter back is the case under test.

    assert twice.__wrapped__ is list  # type: ignore[attr-defined]  # Set by `ignore_arguments`.
    assert twice("key") == []


def test_no_arg_factory_refuses_what_is_not_callable() -> None:
    with pytest.raises(TypeError, match="must be callable"):
        _no_arg_factory(5)  # type: ignore[arg-type]  # The wrong type is the point.
