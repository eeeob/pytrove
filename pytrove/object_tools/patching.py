"""Patching classes in place, unwrapping decorated callables, and walking subclasses."""

from __future__ import annotations as _annotations

import inspect
from typing import TYPE_CHECKING, Any, overload

from .._internal import _iter_unwrap_layers
from ._internal import _install

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from ..typings import _CT


def unwrap_cls(cls: type) -> int:
    """Replace every wrapped attribute of a class with what it wraps, in place.

    Inherited members are unwrapped too: each is set on `cls` itself, so its base
    keeps the wrapped one. Members are read raw (`inspect.getattr_static`), so no
    descriptor getter runs. A `classmethod` or `staticmethod` keeps its kind around
    the unwrapped function. A nested class and a property are left as they are.

    Args:
        cls: The class.

    Returns:
        How many attributes were unwrapped.

    Example:
        >>> import functools
        >>> def logged(func):
        ...     @functools.wraps(func)
        ...     def wrapper(*args):
        ...         return func(*args)
        ...     return wrapper
        >>> class Thing:
        ...     @staticmethod
        ...     @logged
        ...     def one():
        ...         return 1
        >>> unwrap_cls(Thing), Thing.one(), hasattr(Thing.one, "__wrapped__")
        (1, 1, False)
    """
    count = 0

    for name in dir(cls):
        member = inspect.getattr_static(cls, name)

        if isinstance(member, type):
            continue

        if isinstance(member, (classmethod, staticmethod)):
            func = member.__func__

            if not hasattr(func, "__wrapped__"):
                continue

            unwrapped: Any = type(member)(inspect.unwrap(func))
        elif hasattr(member, "__wrapped__"):
            unwrapped = inspect.unwrap(member)
        else:
            continue

        setattr(cls, name, unwrapped)
        count += 1

    return count


def unwrap(obj: Any, *, unwrap_properties: bool = True) -> Any:
    """Peel an object down to its underlying function, through properties, partials and `__wrapped__`.

    The layers may nest in any order: each turn peels whichever one is outermost,
    until none is left. A `classmethod` or `staticmethod` is always peeled. A class
    is returned as it is.

    Args:
        obj: The object.
        unwrap_properties: Whether to take the getter of a `property` or a
            `functools.cached_property`.

    Returns:
        The innermost callable, or `None` for a property without a getter.

    Raises:
        ValueError: If the layers loop back on themselves.
    """
    *_, innermost = _iter_unwrap_layers(obj, unwrap_properties=unwrap_properties)
    return innermost


def patch_into(
    target: type,
    *,
    patch_key: str = "should_patch",
    preserve_old: bool = True,
    setter: Callable[[type, str, Any], None] = setattr,
    unwrap_properties: bool = True,
) -> Callable[[_CT], _CT]:
    """Build a class decorator that copies only marked members onto `target`.

    A member is copied when it, or any layer `unwrap` peels from it, has a truthy
    `patch_key` attribute.
    The decorated class itself is returned unchanged. A replaced member is kept
    raw (a `staticmethod` stays one), as `inspect.getattr_static` reads it.

    Args:
        target: The class to patch.
        patch_key: The marker attribute.
        preserve_old: Whether to keep a replaced member as `old<name>`.
        setter: How to set each member.
        unwrap_properties: Whether to look for the marker under the getter of a
            `property` or a `functools.cached_property`, as `unwrap` does.

    Returns:
        The decorator.

    Example:
        >>> class Target:
        ...     def greet(self):
        ...         return "hi"
        >>> @patch_into(Target)
        ... class Patches:
        ...     def greet(self):
        ...         return "hello"
        ...     greet.should_patch = True
        ...     def ignored(self):
        ...         return "not copied"
        >>> Target().greet(), Target().oldgreet(), hasattr(Target, "ignored")
        ('hello', 'hi', False)
    """

    def apply(current_class: _CT) -> _CT:
        """Copy the marked members.

        Args:
            current_class: The class holding the patches.

        Returns:
            `current_class` unchanged.
        """
        for name, member in current_class.__dict__.items():
            layers = _iter_unwrap_layers(member, unwrap_properties=unwrap_properties)

            if not any(getattr(layer, patch_key, False) for layer in layers):
                continue

            _install(target, name, member, preserve_old=preserve_old, setter=setter)

        return current_class

    return apply


@overload
def patch_cls(patch_class: _CT) -> _CT: ...
@overload
def patch_cls(
    *,
    preserve_old: bool = True,
    setter: Callable[[type, str, Any], None] = setattr,
    include_dunders: tuple[str, ...] = ("__init__",),
) -> Callable[[_CT], _CT]: ...
def patch_cls(
    patch_class: type | None = None,
    *,
    preserve_old: bool = True,
    setter: Callable[[type, str, Any], None] = setattr,
    include_dunders: tuple[str, ...] = ("__init__",),
) -> Any:
    """Copy a class body onto its single base and return the base, directly or as a decorator.

    Dunders are skipped unless listed in `include_dunders`. A replaced member is
    kept raw (a `staticmethod` stays one), as `inspect.getattr_static` reads it.

    A copied method that calls zero-argument `super()` breaks once on the base:
    its `__class__` cell still names the patch class, which the base's instances
    are not instances of, so `super()` raises `TypeError`. Call `self.old<name>()`
    instead, as the example does, or `super(Base, self)` with the base named.

    The result is typed as the patch class, whose members the base now carries,
    so a type checker sees them; at runtime it is the base itself, and an
    instance of the base is not an instance of the patch class.

    Args:
        patch_class: The class holding the patches; omit it to get a decorator.
        preserve_old: Whether to keep a replaced member as `old<name>`.
        setter: How to set each member.
        include_dunders: Dunder members to copy as well.

    Returns:
        The patched base, or a decorator.

    Raises:
        TypeError: If the class does not have exactly one base besides `object`.

    Example:
        >>> class Target:
        ...     def greet(self):
        ...         return "hi"
        >>> @patch_cls
        ... class Target(Target):
        ...     def greet(self):
        ...         return "hello, " + self.oldgreet()
        >>> Target().greet()
        'hello, hi'
    """

    def _apply(cls: type) -> type:
        """Patch `cls`'s base with its body.

        Args:
            cls: The class holding the patches.

        Returns:
            The patched base.

        Raises:
            TypeError: If there is not exactly one base.
        """
        bases = [b for b in cls.__bases__ if b is not object]

        if len(bases) != 1:
            msg = f"{cls.__name__} must inherit from exactly one base, got {[b.__name__ for b in bases]}"
            raise TypeError(msg)

        target = bases[0]

        for name, member in cls.__dict__.items():
            if name.startswith("__") and name.endswith("__") and name not in include_dunders:
                continue

            _install(target, name, member, preserve_old=preserve_old, setter=setter)

        return target

    return _apply(patch_class) if patch_class is not None else _apply


def walk_subclasses(cls: type, include_base: bool = False) -> Iterator[type]:
    """Yield every subclass at any depth, each once even in a diamond, lazily.

    A metaclass such as `type` or `abc.ABCMeta` works too.

    Args:
        cls: The root class.
        include_base: Whether to yield `cls` itself first.

    Yields:
        Each class.

    Example:
        >>> class A: ...
        >>> class B(A): ...
        >>> class C(B): ...
        >>> sorted(cls.__name__ for cls in walk_subclasses(A))
        ['B', 'C']
    """
    seen: set[type] = set()
    # `type.__subclasses__(cls)`, not `cls.__subclasses__()`: on a metaclass the latter finds the
    # unbound `type.__subclasses__` and raises `TypeError` for want of an argument.
    stack = [cls] if include_base else type.__subclasses__(cls)

    while stack:
        current = stack.pop()

        if current in seen:
            continue

        seen.add(current)
        yield current
        stack.extend(type.__subclasses__(current))


__all__ = (
    "unwrap_cls",
    "unwrap",
    "patch_into",
    "patch_cls",
    "walk_subclasses",
)
