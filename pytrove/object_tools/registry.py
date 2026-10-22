"""A base class whose instances register themselves weakly, per subclass."""

from __future__ import annotations as _annotations

import sys
import weakref
from abc import ABC
from typing import TYPE_CHECKING, Any, ClassVar, Generic

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from ._internal import _WeakRegistryKT
from .descriptors import classproperty


class WeakRegistry(ABC, Generic[_WeakRegistryKT]):
    """Instances register themselves in `Cls.__instances__[key]` without being kept alive by it.

    Each subclass gets its own table. Without a key, `id(self)` is used, which
    lasts only while something else holds the instance; `key=None` always
    means "use the id". Pass `allow_duplicate_keys=False` in the class
    statement to refuse a key that is already live:
    `class Widget(WeakRegistry[str], allow_duplicate_keys=False): ...`.

    Attributes:
        __allow_duplicate_keys__: Whether registering a live key replaces it; inherited.
        __instances__: The live instances by key.

    Example:
        >>> class Widget(WeakRegistry[str]):
        ...     pass
        >>> w = Widget("main")
        >>> Widget.__instances__["main"] is w
        True
        >>> del w
        >>> "main" in Widget.__instances__
        False
    """

    __slots__ = ("__weakref__",)
    __allow_duplicate_keys__: ClassVar[bool] = True

    if TYPE_CHECKING:
        # Not a `ClassVar`: one cannot name `_WeakRegistryKT` (PEP 526), and each
        # subclass's table is keyed by its own parameter. An `id` key is an `int`.
        __instances__: weakref.WeakValueDictionary[_WeakRegistryKT | int, Self]
    else:

        @classproperty(cached=True)
        def __instances__(cls) -> weakref.WeakValueDictionary:
            """The class's own weak table, created on first use."""
            return weakref.WeakValueDictionary()

    def __init_subclass__(cls, allow_duplicate_keys: bool | None = None, **kwargs: Any) -> None:
        """Record the class keyword, leaving the inherited value when it is not given.

        Args:
            allow_duplicate_keys: Whether a live key may be replaced.
            **kwargs: Passed on to the parent hook.
        """
        super().__init_subclass__(**kwargs)

        if allow_duplicate_keys is not None:
            cls.__allow_duplicate_keys__ = allow_duplicate_keys

    def __init__(self, key: _WeakRegistryKT | None = None) -> None:
        """Register this instance.

        Args:
            key: Where to register it; `id(self)` when `None`.

        Raises:
            ValueError: If the key is live and duplicates are not allowed.
        """
        registered: _WeakRegistryKT | int = id(self) if key is None else key
        instances = self.__instances__

        if not self.__allow_duplicate_keys__ and instances.get(registered, self) is not self:
            msg = (
                f"{self.__class__.__name__}: key {registered!r} is already registered "
                "and this class does not allow duplicate keys"
            )
            raise ValueError(msg)

        instances[registered] = self


__all__ = ("WeakRegistry",)
