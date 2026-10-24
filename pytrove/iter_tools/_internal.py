"""Helpers private to `iter_tools`."""

from __future__ import annotations as _annotations

from collections.abc import Iterable, MutableSequence
from typing import TYPE_CHECKING, Any, TypeVar, cast

from ..validate_tools import is_container

if TYPE_CHECKING:
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


__all__ = ("_MS", "_items")
