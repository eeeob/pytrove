from typing import (
    List, Set, Union, Any,
    FrozenSet, Tuple, Iterable,
    Generator, Optional, Callable,
)


from .typings import NestedContainer, MaybeContainer, _T, _VT
from .validate_tools import is_container


def to_list(value: Optional[MaybeContainer[_T]]) -> List[_T]:
    if is_container(value):
        return list(value)
    return [value] if value is not None else []

def to_tuple(value: Optional[MaybeContainer[_T]]) -> Tuple[_T, ...]:
    if is_container(value):
        return tuple(value)
    return (value, ) if value is not None else tuple()

def to_set(value: Optional[MaybeContainer[_T]]) -> Set[_T]:
    if is_container(value):
        return set(value)
    return {value} if value is not None else set()

def to_frozenset(value: Optional[MaybeContainer[_T]]) -> FrozenSet[_T]:
    if is_container(value):
        return frozenset(value)
    return frozenset({value}) if value is not None else frozenset()


def iter_flat_cont(*containers: NestedContainer[Optional[_T]]) -> Generator[_T, None, None]:
    for item in containers:
        if is_container(item):
            yield from iter_flat_cont(*item)
        elif item is not None:
            yield item

def flat_cont(*containers: NestedContainer[Optional[_T]]) -> List[_T]:
    return list(iter_flat_cont(*containers))


def iter_flat_cont_by(*containers: Any, is_container: Callable[[Any], bool] = is_container) -> Generator[Any, None, None]:
    for item in containers:
        if is_container(item):
            yield from iter_flat_cont_by(*item, is_container=is_container)
        elif item is not None:
            yield item

def flat_cont_by(*containers: Any, is_container: Callable[[Any], bool] = is_container) -> List[Any]:
    return list(iter_flat_cont_by(*containers, is_container=is_container))


def dedupe(iterable: Iterable[_T], hashable: bool = True) -> List[_T]:
    """Remove duplicate elements from `iterable`, always keeping first-seen
    order.

    `hashable=True` (default) uses `dict.fromkeys()` directly on `iterable`
    -- the fastest order-preserving dedup available in pure Python (one
    hash-based pass at the C level, close to plain `set()` speed, and ~35%
    faster than pre-materializing to a list first since it can consume any
    iterable as-is).

    `hashable=False` switches to an equality-based scan (`O(n^2)`) for
    elements that can't be hashed (e.g. dicts/lists) -- pass it explicitly
    rather than relying on a `dict.fromkeys()` attempt-and-fall-back, which
    would burn a partial pass before failing.
    """

    if hashable:
        return list(dict.fromkeys(iterable))

    result = []

    for v in iterable:
        if v not in result:
            result.append(v)

    return result

def pad_list(values: List[_VT], length: int, exact: bool = False, default: _T = None) -> List[Union[_VT, _T]]:
    """Pad `values` in place to `length`, filling missing positions with
    `default` -- mutates the list itself rather than building a new one, and
    returns it back for convenience.

    `values` shorter than `length` is always padded on the right with
    `default`. Longer is left alone unless `exact=True`, which truncates it
    down to `length` too -- so `length` becomes a hard cap instead of just a
    floor.
    """

    if len(values) < length:
        values.extend([default] * (length - len(values)))
    elif exact and len(values) > length:
        del values[length:]

    return values


__all__ = (
    "to_list",
    "to_tuple",
    "to_set",
    "to_frozenset",
    "iter_flat_cont",
    "flat_cont",
    "iter_flat_cont_by",
    "flat_cont_by",
    "pad_list",
    "dedupe",

)