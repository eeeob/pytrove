"""Helpers private to `data_tools`: checking and adapting default factories."""

from __future__ import annotations as _annotations

import weakref
from collections.abc import MutableMapping
from typing import TYPE_CHECKING, Any, Final, cast

from ..._internal import _ignore_arguments
from ...typings import _KT, _VT

if TYPE_CHECKING:
    from collections.abc import Callable

_ADAPTERS: Final[weakref.WeakValueDictionary[int, Callable[..., Any]]] = (
    weakref.WeakValueDictionary()
)
"""The adapters `_no_arg_factory` made, by `id`, so that only those are recognised when handed back."""


class _KeyFactoryMixin(MutableMapping[_KT, _VT]):
    """The keyed-factory behaviour the two weak dicts share; it goes before their base."""

    def __init__(self, default_factory: Callable[[_KT], _VT]) -> None:
        """Start empty.

        Args:
            default_factory: Builds a value from its key.

        Raises:
            TypeError: If it is not callable.
        """
        _check_factory(default_factory)
        super().__init__()
        self.default_factory = default_factory

    def __getitem__(self, key: _KT) -> _VT:
        """Return the value, building and storing one when missing (or, for weak values, collected).

        Args:
            key: The key.

        Returns:
            The value.
        """
        try:
            return super().__getitem__(key)
        except KeyError:
            value = self.default_factory(key)
            self[key] = value
            return value

    def __call__(self, key: _KT) -> _VT:
        """Look a key up, building it when missing.

        Args:
            key: The key.

        Returns:
            Its value.
        """
        return self[key]


def _check_factory(default_factory: object) -> None:
    """Refuse a default factory that cannot be called.

    Args:
        default_factory: The factory to check.

    Raises:
        TypeError: If it is not callable.
    """
    if not callable(default_factory):
        msg = "default_factory must be callable"
        raise TypeError(msg)


def _no_arg_factory(default_factory: Callable[[], _VT]) -> Callable[[Any], _VT]:
    """Adapt a zero-argument factory to the one-argument form the keyed dicts call.

    An adapter this function made, coming back from a caller rebuilding a dict
    out of its `default_factory`, is returned as it is rather than wrapped
    twice. Any other `__wrapped__` (a decorator, an `lru_cache`) is kept.

    Args:
        default_factory: The zero-argument factory.

    Returns:
        A one-argument factory that ignores its argument.

    Raises:
        TypeError: If the factory is not callable.
    """
    if _ADAPTERS.get(id(default_factory)) is default_factory:
        # One of ours: it already takes, and ignores, the key.
        return cast("Callable[[Any], _VT]", default_factory)

    _check_factory(default_factory)
    adapter = _ignore_arguments(default_factory)
    _ADAPTERS[id(adapter)] = adapter
    return adapter


__all__ = ("_KeyFactoryMixin", "_check_factory", "_no_arg_factory")
