"""Helpers private to `iter_tools`."""

from __future__ import annotations as _annotations

from collections.abc import Iterable, MutableSequence
from typing import TYPE_CHECKING, Any, TypeVar, cast

from ..validate_tools import is_container, is_mapping

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from ..typings import MaybeContainer, _T

_MS = TypeVar("_MS", bound=MutableSequence[Any])
"""A mutable sequence, kept with its exact type through `shuffle`."""


def _items(value: MaybeContainer[_T] | None) -> Iterable[_T]:
    """Return what the `to_*` converters collect: a container's items, one value, or nothing.

    Args:
        value: A container, a single value, or `None`.

    Returns:
        The container itself, `(value,)` for a single value, or `()` for `None`.
    """
    if value is None:
        return ()

    # `MaybeContainer[_T]` means a container of `_T` or a single `_T`. An
    # unconstrained `_T` could itself be a container, so the checker cannot
    # tell the two apart on either branch; the alias's contract does.
    return cast("Iterable[_T]", value) if is_container(value) else (cast("_T", value),)


def _iter_flat(
    items: Iterable[Any], is_container: Callable[[Any], bool], exclude_none: bool
) -> Generator[Any, None, None]:
    """Yield the leaves under `items`, one level of the flatteners' walk.

    Each container is iterated, never unpacked, so a leaf is yielded as soon
    as it is reached, even from an endless or failing iterator.

    Args:
        items: The items of one level.
        is_container: Decides, per item, whether to descend into it.
        exclude_none: Whether to drop `None` leaves.

    Yields:
        Each leaf, depth first, in order.
    """
    for item in items:
        if is_container(item):
            yield from _iter_flat(item, is_container, exclude_none)
        elif not exclude_none or item is not None:
            yield item


def _iter_flat_map(items: Iterable[Any], exclude_none: bool) -> Generator[Any, None, None]:
    """Yield the keys and leaves under `items`, one level of `iter_flat_map`'s walk.

    A mapping is walked as its `(key, value)` pairs, each a container itself.

    Args:
        items: The items of one level.
        exclude_none: Whether to drop `None` leaves.

    Yields:
        Each key and leaf, depth first, in order.
    """
    for item in items:
        if is_mapping(item):
            yield from _iter_flat_map(item.items(), exclude_none)
        elif is_container(item):
            yield from _iter_flat_map(item, exclude_none)
        elif not exclude_none or item is not None:
            yield item


__all__ = ("_MS", "_items", "_iter_flat", "_iter_flat_map")
