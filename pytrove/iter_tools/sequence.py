"""Deduplicating, padding and shuffling sequences."""

from __future__ import annotations as _annotations

import random
from collections.abc import Iterable, MutableSequence
from typing import TYPE_CHECKING, Any, cast, overload

if TYPE_CHECKING:
    from ..typings import _T, _VT
    from ._internal import _MS


def dedupe(iterable: Iterable[_T], hashable: bool = True) -> list[_T]:
    """Remove duplicates, keeping first-seen order.

    Args:
        iterable: The values to deduplicate; consumed once.
        hashable: Whether the values are hashable. `False` switches to an
            equality scan, `O(n^2)`, for values such as dicts and lists.

    Returns:
        Each distinct value once, in the order first seen.

    Example:
        >>> dedupe([3, 1, 3, 2, 1])
        [3, 1, 2]
        >>> dedupe([{"a": 1}, {"a": 1}], hashable=False)
        [{'a': 1}]
    """
    if hashable:
        return list(dict.fromkeys(iterable))

    result: list[_T] = []

    for v in iterable:
        if v not in result:
            result.append(v)

    return result


def pad_list(
    values: list[_VT], length: int, exact: bool = False, default: _T | None = None
) -> list[_VT | _T | None]:
    """Pad `values` in place up to `length`, and return it.

    Args:
        values: The list to pad; it is mutated.
        length: The length to reach.
        exact: Whether to also truncate a longer list down to `length`.
        default: The value to pad with.

    Returns:
        `values` itself.

    Example:
        >>> pad_list([1, 2], 4)
        [1, 2, None, None]
        >>> pad_list([1, 2, 3], 2, exact=True, default=0)
        [1, 2]
    """
    # Padded in place, so the caller's list gains `default`s of another type:
    # the return type states the widened content the input type cannot.
    padded = cast("list[_VT | _T | None]", values)

    if len(padded) < length:
        padded.extend([default] * (length - len(padded)))
    elif exact and len(padded) > length:
        del padded[length:]

    return padded


@overload
def shuffle(seq: _MS) -> _MS: ...
@overload
def shuffle(seq: Iterable[_T]) -> list[_T]: ...
def shuffle(seq: Iterable[Any]) -> MutableSequence[Any]:
    """Shuffle a mutable sequence in place, or a copy of any other iterable.

    Args:
        seq: The values to shuffle.

    Returns:
        `seq` itself when it is a mutable sequence, otherwise a new shuffled list.
    """
    if not isinstance(seq, MutableSequence):
        seq = list(seq)

    if seq:
        random.shuffle(seq)

    return seq


__all__ = (
    "dedupe",
    "pad_list",
    "shuffle",
)
