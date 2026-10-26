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
        hashable: Whether every value is hashable. `False` accepts unhashable
            values such as dicts and lists too: hashable ones are still found
            by hash, and only each unhashable one costs a scan of the result.

    Returns:
        Each distinct value once, in the order first seen.

    Raises:
        TypeError: If a value is unhashable while `hashable` is `True`.

    Example:
        >>> dedupe([3, 1, 3, 2, 1])
        [3, 1, 2]
        >>> dedupe([{"a": 1}, {"a": 1}], hashable=False)
        [{'a': 1}]
    """
    if hashable:
        return list(dict.fromkeys(iterable))

    result: list[_T] = []
    seen: set[Any] = set()
    unhashable: list[_T] = []

    for v in iterable:
        try:
            # An unhashable value may still equal a hashable one (`{1} == frozenset({1})`).
            if v in seen or v in unhashable:
                continue

            seen.add(v)
        except TypeError:
            if v in result:
                continue

            unhashable.append(v)

        result.append(v)

    return result


# Without `default` the padding is `None`; a `None` default could not solve `_T`.
@overload
def pad_list(values: list[_VT], length: int, exact: bool = False) -> list[_VT | None]: ...
@overload
def pad_list(values: list[_VT], length: int, exact: bool, default: _T) -> list[_VT | _T]: ...
@overload
def pad_list(
    values: list[_VT], length: int, exact: bool = False, *, default: _T
) -> list[_VT | _T]: ...
def pad_list(
    values: list[_VT], length: int, exact: bool = False, default: _T | None = None
) -> list[_VT | _T | None]:
    """Pad `values` in place up to `length`, and return it.

    Args:
        values: The list to pad; it is mutated.
        length: The length to reach; not negative.
        exact: Whether to also truncate a longer list down to `length`.
        default: The value to pad with.

    Returns:
        `values` itself.

    Raises:
        ValueError: If `length` is negative.

    Example:
        >>> pad_list([1, 2], 4)
        [1, 2, None, None]
        >>> pad_list([1, 2, 3], 2, exact=True, default=0)
        [1, 2]
    """
    # Padded in place, so the caller's list gains `default`s of another type:
    # the return type states the widened content the input type cannot.
    if length < 0:
        msg = f"length must not be negative, not {length}"
        raise ValueError(msg)

    padded = cast("list[_VT | _T | None]", values)

    if len(padded) < length:
        padded.extend([default] * (length - len(padded)))
    elif exact and len(padded) > length:
        del padded[length:]

    return padded


@overload
def shuffle(seq: _MS, rng: random.Random | None = None) -> _MS: ...
@overload
def shuffle(seq: Iterable[_T], rng: random.Random | None = None) -> list[_T]: ...
def shuffle(seq: Iterable[Any], rng: random.Random | None = None) -> MutableSequence[Any]:
    """Shuffle a mutable sequence in place, or a copy of any other iterable.

    Args:
        seq: The values to shuffle.
        rng: The generator to draw from, for a reproducible order; `None`
            uses the global `random` one.

    Returns:
        `seq` itself when it is a mutable sequence, otherwise a new shuffled list.
    """
    if not isinstance(seq, MutableSequence):
        seq = list(seq)

    if seq:
        (random if rng is None else rng).shuffle(seq)

    return seq


__all__ = (
    "dedupe",
    "pad_list",
    "shuffle",
)
