"""Patching classes in place, unwrapping decorated callables, and walking subclasses."""

from __future__ import annotations as _annotations

import inspect
from typing import TYPE_CHECKING, Any, overload

from .._internal import _iter_unwrap_layers

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from ..typings import _CT


def unwrap_cls(cls: type) -> int:
    """Replace every wrapped attribute of a class with what it wraps, in place.

    Args:
        cls: The class.

    Returns:
        How many attributes were unwrapped.
    """
    count = 0

    for name in dir(cls):
        method = getattr(cls, name)

        if hasattr(method, "__wrapped__"):
            setattr(cls, name, inspect.unwrap(method))
            count += 1

    return count


def unwrap(obj: Any, with_prop: bool = True) -> Any:
    """Peel an object down to its underlying function, through properties, partials and `__wrapped__`.

    The layers may nest in any order: each turn peels whichever one is outermost,
    until none is left. A class is returned as it is.

    Args:
        obj: The object.
        with_prop: Whether to take a property's getter.

    Returns:
        The innermost callable, or `None` for a property without a getter.

    Raises:
        ValueError: If the layers loop back on themselves.
    """
    *_, innermost = _iter_unwrap_layers(obj, with_prop=with_prop)
    return innermost


def patch_into(
    target: type,
    *,
    patch_key: str = "should_patch",
    preserve_old: bool = True,
    setter: Callable[[type, str, Any], None] = setattr,
) -> Callable[[_CT], _CT]:
    """Build a class decorator that copies only marked members onto `target`.

    A member is copied when it, or any layer `unwrap` peels from it, has a truthy
    `patch_key` attribute.
    The decorated class itself is returned unchanged.

    Args:
        target: The class to patch.
        patch_key: The marker attribute.
        preserve_old: Whether to keep a replaced member as `old<name>`.
        setter: How to set each member.

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
            layers = _iter_unwrap_layers(member, with_prop=True)

            if not any(getattr(layer, patch_key, False) for layer in layers):
                continue

            if preserve_old and hasattr(target, name):
                setattr(target, f"old{name}", getattr(target, name))

            setter(target, name, member)

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

    Dunders are skipped unless listed in `include_dunders`.

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

            if preserve_old and hasattr(target, name):
                setattr(target, f"old{name}", getattr(target, name))

            setter(target, name, member)

        return target

    return _apply(patch_class) if patch_class is not None else _apply


def walk_subclasses(cls: type, include_base: bool = False) -> Iterator[type]:
    """Yield every subclass at any depth, each once even in a diamond.

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
    stack = [cls] if include_base else list(cls.__subclasses__())

    while stack:
        current = stack.pop()

        if current in seen:
            continue

        seen.add(current)
        yield current
        stack.extend(current.__subclasses__())


__all__ = (
    "unwrap_cls",
    "unwrap",
    "patch_into",
    "patch_cls",
    "walk_subclasses",
)
