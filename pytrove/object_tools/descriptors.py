"""Descriptors: class-level properties, hybrid methods, and read-only class attributes."""

from __future__ import annotations as _annotations

import inspect
import sys
from functools import partial
from types import MethodType
from typing import TYPE_CHECKING, Any, Generic, overload

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from ..typings import _T, _VT
from ..data_tools.mappings import KeyDefaultWeakKeyDict

if TYPE_CHECKING:
    from collections.abc import Callable


class classproperty(Generic[_T, _VT]):
    """A property whose getter receives the class, readable as `Cls.attr`.

    Usable bare (`@classproperty`) or with options (`@classproperty(cached=True)`).
    With `cached`, the value is computed once per owning class, so a subclass
    gets its own.

    Attributes:
        call: The getter, or a per-class cache wrapping it.
        doc: The documentation; the getter's own by default.

    Example:
        >>> class Model:
        ...     table = "models"
        ...     @classproperty
        ...     def key(cls):
        ...         return cls.table.upper()
        >>> Model.key
        'MODELS'
        >>> Model().key
        'MODELS'
    """

    __slots__ = "call", "doc"

    @overload
    def __new__(
        cls,
        fget: Callable[[type[_T]], _VT],
        *,
        doc: str | None = None,
        cached: bool = False,
    ) -> classproperty[_T, _VT]: ...
    @overload
    def __new__(
        cls,
        fget: None = None,
        *,
        doc: str | None = None,
        cached: bool = False,
    ) -> Callable[[Callable[[type[_T]], _VT]], classproperty[_T, _VT]]: ...
    def __new__(
        cls, fget: Callable[..., Any] | None = None, *, doc: str | None = None, cached: bool = False
    ) -> Any:
        """Create the property, or a decorator awaiting the getter when called with options only.

        Args:
            fget: The getter.
            doc: The documentation.
            cached: Whether to compute once per class.

        Returns:
            The property, or a decorator.
        """
        if fget is None:
            return partial(cls, doc=doc, cached=cached)

        return super().__new__(cls)

    def __init__(
        self, fget: Callable[[type[_T]], _VT], *, doc: str | None = None, cached: bool = False
    ) -> None:
        """Store the getter.

        Args:
            fget: The getter.
            doc: The documentation.
            cached: Whether to compute once per class.
        """
        self.call = KeyDefaultWeakKeyDict(fget) if cached else fget
        self.doc = fget.__doc__ if doc is None else doc

    @property
    def __doc__(self) -> str | None:
        """The property's documentation."""
        return self.doc

    @overload
    def __get__(self, instance: Any, owner: None) -> Self: ...
    @overload
    def __get__(self, instance: Any, owner: type[_T]) -> _VT: ...
    def __get__(self, instance: Any, owner: type[_T] | None) -> Any:
        """Compute the value for the owning class.

        Args:
            instance: Ignored; the class decides.
            owner: The class looked up on.

        Returns:
            The value, or the property itself when there is no owner.
        """
        if owner is None:
            return self

        value = self.call(owner)

        if value is self and isinstance(self.call, KeyDefaultWeakKeyDict):
            self.call.pop(owner, None)

        return value


if TYPE_CHECKING:
    # Type checkers treat it as `classmethod`; the instance-receiving behaviour cannot be expressed in typing.
    hybridmethod = classmethod
else:

    class hybridmethod(classmethod):
        """A method that receives the class on `Cls.method()` and the instance on `obj.method()`.

        Example:
            >>> class Node:
            ...     @hybridmethod
            ...     def who(self_or_cls):
            ...         return "class" if isinstance(self_or_cls, type) else "instance"
            >>> Node.who()
            'class'
            >>> Node().who()
            'instance'
        """

        def __get__(self, instance: Any, owner: type | None = None, /) -> MethodType:
            """Bind to the instance when there is one, else to the class.

            Args:
                instance: The instance looked up on, or `None`.
                owner: The class.

            Returns:
                The bound method.
            """
            return MethodType(self.__func__, owner if instance is None else instance)


class FrozenClassAttrs:
    """A base whose instances cannot shadow a class attribute.

    A data descriptor is not shadowed by an assignment, so it stays assignable:
    a property with a setter and a `__slots__` member work as usual. Assigning on
    the class itself (`Config.name = ...`) is not affected.

    Example:
        >>> class Config(FrozenClassAttrs):
        ...     name = "default"
        >>> Config().name = "other"
        Traceback (most recent call last):
            ...
        AttributeError: Cannot override class attribute 'name' from instance
    """

    def __setattr__(self, name: str, value: Any) -> None:
        """Set an instance attribute unless the class already defines that name.

        Args:
            name: The attribute.
            value: Its value.

        Raises:
            AttributeError: If the class defines `name` as anything but a data descriptor.
        """
        try:
            # Read raw: `hasattr` would run a `classproperty` getter, and treat one that raises
            # `AttributeError` as absent.
            attr = inspect.getattr_static(type(self), name)
        except AttributeError:
            pass
        else:
            if not hasattr(type(attr), "__set__"):
                msg = f"Cannot override class attribute '{name}' from instance"
                raise AttributeError(msg)

        super().__setattr__(name, value)


__all__ = (
    "classproperty",
    "hybridmethod",
    "FrozenClassAttrs",
)
