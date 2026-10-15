"""Class patching, unwrapping and secret generation."""

from __future__ import annotations as _annotations

import functools
import inspect
import secrets
import string
from collections.abc import Callable, Iterator
from typing import Any, overload

from .typings import _CT


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


def generate_secret(
    length: int,
    use_upper: bool = True,
    use_lower: bool = True,
    use_digits: bool = True,
    use_symbols: bool = True,
) -> str:
    """Generate a random secret with at least one character from each enabled set.

    Args:
        length: The secret's length.
        use_upper: Whether to use uppercase letters.
        use_lower: Whether to use lowercase letters.
        use_digits: Whether to use digits.
        use_symbols: Whether to use punctuation.

    Returns:
        The secret, drawn with `secrets`.

    Raises:
        ValueError: If `length` is not positive, no set is enabled, or `length`
            is shorter than the number of enabled sets.
    """
    if length <= 0:
        msg = "Password length must be greater than 0"
        raise ValueError(msg)

    sets = [
        chars for enabled, chars in (
            (use_lower, string.ascii_lowercase),
            (use_upper, string.ascii_uppercase),
            (use_digits, string.digits),
            (use_symbols, "!@#$%^&*()-_=+[]{};:,.<>?/"),
        ) if enabled
    ]

    if not sets:
        msg = "At least one character set must be enabled"
        raise ValueError(msg)

    if length < len(sets):
        msg = "Length too small for selected options"
        raise ValueError(msg)

    all_chars = "".join(sets)
    password = [secrets.choice(chars) for chars in sets]
    password += [secrets.choice(all_chars) for _ in range(length - len(sets))]
    secrets.SystemRandom().shuffle(password)
    return "".join(password)


def unwrap(obj: Any, with_prop: bool = True) -> Any:
    """Peel an object down to its underlying function, through properties, partialmethods and `__wrapped__`.

    Args:
        obj: The object.
        with_prop: Whether to take a property's getter.

    Returns:
        The innermost callable.
    """
    if with_prop and isinstance(obj, property):
        obj = obj.fget

    while isinstance(obj, functools.partialmethod):
        obj = obj.func

    return inspect.unwrap(obj)


def patch_into(
    target: type,
    *,
    patch_key: str = "should_patch",
    preserve_old: bool = True,
    setter: Callable[[type, str, Any], None] = setattr,
) -> Callable[[_CT], _CT]:
    """Build a class decorator that copies only marked members onto `target`.

    A member is copied when it (unwrapped) has a truthy `patch_key` attribute.
    The decorated class itself is returned unchanged.

    Args:
        target: The class to patch.
        patch_key: The marker attribute.
        preserve_old: Whether to keep a replaced member as `old<name>`.
        setter: How to set each member.

    Returns:
        The decorator.
    """

    def apply(current_class: _CT) -> _CT:
        """Copy the marked members.

        Args:
            current_class: The class holding the patches.

        Returns:
            `current_class` unchanged.
        """
        for name, member in current_class.__dict__.items():
            if not getattr(unwrap(member), patch_key, False):
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
    "generate_secret",
    "unwrap",
    "patch_into",
    "patch_cls",
    "walk_subclasses",
)
