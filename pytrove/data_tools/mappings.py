"""Dictionaries that build a missing value from its key."""

from __future__ import annotations as _annotations

import weakref
from typing import TYPE_CHECKING

from ..typings import _KT, _VT
from ._internal import _KeyFactoryMixin, _check_factory, _no_arg_factory

if TYPE_CHECKING:
    from collections.abc import Callable


class KeyDefaultDict(dict[_KT, _VT]):
    """A dict that builds a missing value from its key, like `defaultdict` with the key passed.

    Attributes:
        default_factory: Called with a missing key; its result is stored and returned.

    Example:
        >>> d = KeyDefaultDict(str.upper)
        >>> d["a"]
        'A'
        >>> d
        {'a': 'A'}
    """

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

    def __missing__(self, key: _KT) -> _VT:
        """Build, store and return the value for a missing key.

        Args:
            key: The missing key.

        Returns:
            The new value.
        """
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


class KeyDefaultWeakValueDict(_KeyFactoryMixin[_KT, _VT], weakref.WeakValueDictionary[_KT, _VT]):
    """A `WeakValueDictionary` that builds a missing value from its key; calling it looks a key up.

    Attributes:
        default_factory: Called with a missing key.
    """


class DefaultWeakValueDict(KeyDefaultWeakValueDict[_KT, _VT]):
    """A `KeyDefaultWeakValueDict` whose factory takes no arguments."""

    def __init__(self, default_factory: Callable[[], _VT]) -> None:
        """Start empty.

        Args:
            default_factory: Builds a value with no arguments.

        Raises:
            TypeError: If it is not callable.
        """
        super().__init__(_no_arg_factory(default_factory))


class KeyDefaultWeakKeyDict(_KeyFactoryMixin[_KT, _VT], weakref.WeakKeyDictionary[_KT, _VT]):
    """A `WeakKeyDictionary` that builds a missing value from its key; calling it looks a key up.

    Attributes:
        default_factory: Called with a missing key.
    """


class DefaultWeakKeyDict(KeyDefaultWeakKeyDict[_KT, _VT]):
    """A `KeyDefaultWeakKeyDict` whose factory takes no arguments."""

    def __init__(self, default_factory: Callable[[], _VT]) -> None:
        """Start empty.

        Args:
            default_factory: Builds a value with no arguments.

        Raises:
            TypeError: If it is not callable.
        """
        super().__init__(_no_arg_factory(default_factory))


__all__ = (
    "KeyDefaultDict",
    "KeyDefaultWeakValueDict",
    "DefaultWeakValueDict",
    "KeyDefaultWeakKeyDict",
    "DefaultWeakKeyDict",
)
