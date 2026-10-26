"""`data_tools._internal.factories`: adapting zero-argument factories."""

from __future__ import annotations as _annotations

import functools
import gc
import weakref
from typing import TYPE_CHECKING, Any

import pytest

from pytrove.data_tools import DefaultWeakKeyDict
from pytrove.data_tools._internal import _KeyFactoryMixin, _check_factory, _no_arg_factory
from pytrove.data_tools._internal.factories import _ADAPTERS

if TYPE_CHECKING:
    from collections.abc import Callable


def test_no_arg_factory_ignores_the_key_and_keeps_the_original() -> None:
    adapted = _no_arg_factory(list)

    assert adapted("any key") == []
    assert adapted.__wrapped__ is list  # type: ignore[attr-defined]  # Set by `ignore_arguments`.


def test_no_arg_factory_does_not_wrap_an_adapter_twice() -> None:
    once = _no_arg_factory(list)
    twice = _no_arg_factory(once)  # type: ignore[arg-type]  # Handing the adapter back is the case under test.

    assert twice is once
    assert twice.__wrapped__ is list  # type: ignore[attr-defined]  # Set by `ignore_arguments`.
    assert twice("key") == []


def test_no_arg_factory_refuses_what_is_not_callable() -> None:
    with pytest.raises(TypeError, match="must be callable"):
        _no_arg_factory(5)  # type: ignore[arg-type]  # The wrong type is the point.


class _Key:
    """Weak-referenceable and hashable."""


def _decorated(func: Callable[[], Any]) -> Callable[[], Any]:
    @functools.wraps(func)
    def wrapper() -> Any:
        return ["decorated"]

    return wrapper


def test_no_arg_factory_keeps_a_decorated_factory() -> None:
    factory = _decorated(list)
    adapted = _no_arg_factory(factory)

    assert adapted("key") == ["decorated"]
    assert adapted.__wrapped__ is factory  # type: ignore[attr-defined]  # Set by `ignore_arguments`.

    key = _Key()
    assert DefaultWeakKeyDict(factory)[key] == ["decorated"]


def test_no_arg_factory_keeps_an_lru_cached_factory() -> None:
    calls: list[int] = []

    @functools.cache
    def cached() -> list[int]:
        calls.append(1)
        return []

    adapted = _no_arg_factory(cached)

    assert adapted("a") is adapted("b")
    assert calls == [1]


def test_no_arg_factory_does_not_unwrap_a_non_callable_with_a_wrapped() -> None:
    class Holder:
        __wrapped__ = staticmethod(list)

    with pytest.raises(TypeError, match="must be callable"):
        _no_arg_factory(Holder())  # type: ignore[arg-type]  # The wrong type is the point.


def test_adapters_registry_holds_each_adapter_weakly_by_id() -> None:
    adapted = _no_arg_factory(list)
    assert isinstance(_ADAPTERS, weakref.WeakValueDictionary)
    assert _ADAPTERS[id(adapted)] is adapted

    key = id(adapted)
    del adapted
    gc.collect()

    assert _ADAPTERS.get(key) is None


def test_check_factory_accepts_a_callable_and_refuses_anything_else() -> None:
    _check_factory(list)

    with pytest.raises(TypeError, match="default_factory must be callable"):
        _check_factory("x")


def test_key_factory_mixin_builds_stores_and_calls() -> None:
    class Keyed(_KeyFactoryMixin[str, str], weakref.WeakKeyDictionary):  # type: ignore[type-arg]  # Only the mixin is under test.
        pass

    with pytest.raises(TypeError, match="must be callable"):
        Keyed(5)  # type: ignore[arg-type]  # The wrong type is the point.

    calls: list[Any] = []
    d = Keyed(lambda k: calls.append(k) or "v")
    key = _Key()

    assert d[key] == "v"  # type: ignore[index]  # A weak-key dict needs a weak-referenceable key.
    assert d(key) == "v"  # type: ignore[arg-type]  # Same key.
    assert calls == [key]
    assert d.default_factory is not None
