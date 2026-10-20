"""Turning one value or a container into a list, tuple or set."""

from __future__ import annotations as _annotations

from ..typings import MaybeContainer, _T
from ._internal import _items


def to_list(value: MaybeContainer[_T] | None) -> list[_T]:
    """Turn a value or a container into a list.

    Args:
        value: A container, a single value, or `None`.

    Returns:
        The container's items, `[value]` for a single value, or `[]` for `None`.
    """
    return list(_items(value))


def to_tuple(value: MaybeContainer[_T] | None) -> tuple[_T, ...]:
    """Turn a value or a container into a tuple, as `to_list` does.

    Args:
        value: A container, a single value, or `None`.

    Returns:
        The container's items, `(value,)` for a single value, or `()` for `None`.
    """
    return tuple(_items(value))


def to_set(value: MaybeContainer[_T] | None) -> set[_T]:
    """Turn a value or a container into a set, as `to_list` does.

    Args:
        value: A container, a single value, or `None`.

    Returns:
        The container's items, `{value}` for a single value, or an empty set for `None`.
    """
    return set(_items(value))


def to_frozenset(value: MaybeContainer[_T] | None) -> frozenset[_T]:
    """Turn a value or a container into a frozenset, as `to_list` does.

    Args:
        value: A container, a single value, or `None`.

    Returns:
        The container's items, a one-item frozenset for a single value, or an empty one for `None`.
    """
    return frozenset(_items(value))


__all__ = (
    "to_list",
    "to_tuple",
    "to_set",
    "to_frozenset",
)
