"""Turning one value or a container into a list, tuple or set."""

from __future__ import annotations as _annotations

from ..typings import MaybeContainer, _T
from ..validate_tools import is_container


def to_list(value: MaybeContainer[_T] | None) -> list[_T]:
    """Turn a value or a container into a list.

    Args:
        value: A container, a single value, or `None`.

    Returns:
        The container's items, `[value]` for a single value, or `[]` for `None`.
    """
    if is_container(value):
        return list(value)
    return [value] if value is not None else []


def to_tuple(value: MaybeContainer[_T] | None) -> tuple[_T, ...]:
    """Turn a value or a container into a tuple, as `to_list` does.

    Args:
        value: A container, a single value, or `None`.

    Returns:
        The container's items, `(value,)` for a single value, or `()` for `None`.
    """
    if is_container(value):
        return tuple(value)
    return (value,) if value is not None else ()


def to_set(value: MaybeContainer[_T] | None) -> set[_T]:
    """Turn a value or a container into a set, as `to_list` does.

    Args:
        value: A container, a single value, or `None`.

    Returns:
        The container's items, `{value}` for a single value, or an empty set for `None`.
    """
    if is_container(value):
        return set(value)
    return {value} if value is not None else set()


def to_frozenset(value: MaybeContainer[_T] | None) -> frozenset[_T]:
    """Turn a value or a container into a frozenset, as `to_list` does.

    Args:
        value: A container, a single value, or `None`.

    Returns:
        The container's items, a one-item frozenset for a single value, or an empty one for `None`.
    """
    if is_container(value):
        return frozenset(value)
    return frozenset((value,)) if value is not None else frozenset()


__all__ = (
    "to_list",
    "to_tuple",
    "to_set",
    "to_frozenset",
)
