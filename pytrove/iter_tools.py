from typing import (
    List, Set, Union, Any,
    FrozenSet, Tuple, Iterable,
    Generator, Optional, Callable,
    Mapping, overload, TypeVar,
)


from .typings import NestedContainer, NestedContainerMappingValue, MaybeContainer, _True, _False, _T, _KT, _VT
from .validate_tools import is_container, is_mapping

_MT = TypeVar("_MT")  # first_map's single-iterable overload: func's own argument type


def to_list(value: Optional[MaybeContainer[_T]]) -> List[_T]:
    """`value` as a list: itself if it's a container, `[value]` otherwise,
    `[]` for None."""

    if is_container(value):
        return list(value)
    return [value] if value is not None else []

def to_tuple(value: Optional[MaybeContainer[_T]]) -> Tuple[_T, ...]:
    """to_list, as a tuple."""

    if is_container(value):
        return tuple(value)
    return (value, ) if value is not None else tuple()

def to_set(value: Optional[MaybeContainer[_T]]) -> Set[_T]:
    """to_list, as a set."""

    if is_container(value):
        return set(value)
    return {value} if value is not None else set()

def to_frozenset(value: Optional[MaybeContainer[_T]]) -> FrozenSet[_T]:
    """to_list, as a frozenset."""

    if is_container(value):
        return frozenset(value)
    return frozenset((value, )) if value is not None else frozenset()


@overload
def iter_flat_cont(*containers: NestedContainer[Optional[_T]], exclude_none: _True = True) -> Generator[_T, None, None]: ...
@overload
def iter_flat_cont(*containers: NestedContainer[_T], exclude_none: _False) -> Generator[_T, None, None]: ...
def iter_flat_cont(*containers, exclude_none = True):
    """Yield every leaf under `containers`, flattening nested ones as it goes.

    `exclude_none` defaults to True, dropping a None wherever one turns up.
    Pass False to keep it: a None is then a leaf like any other.
    """

    for item in containers:
        if is_container(item):
            yield from iter_flat_cont(*item, exclude_none=exclude_none)
        elif not exclude_none or item is not None:
            yield item


@overload
def flat_cont(*containers: NestedContainer[Optional[_T]], exclude_none: _True = True) -> List[_T]: ...
@overload
def flat_cont(*containers: NestedContainer[_T], exclude_none: _False) -> List[_T]: ...
def flat_cont(*containers, exclude_none = True):
    """iter_flat_cont, collected into a list."""
    return list(iter_flat_cont(*containers, exclude_none=exclude_none))

@overload
def iter_flat_map(*containers: Mapping[_KT, NestedContainerMappingValue[_KT, Optional[_VT]]], exclude_none: _True = True) -> Generator[Union[_KT, _VT], None, None]: ...
@overload
def iter_flat_map(*containers: Mapping[_KT, NestedContainerMappingValue[_KT, _VT]], exclude_none: _False) -> Generator[Union[_KT, _VT], None, None]: ...
@overload
def iter_flat_map(*containers: NestedContainer[Optional[_T]], exclude_none: _True = True) -> Generator[_T, None, None]: ...
@overload
def iter_flat_map(*containers: NestedContainer[_T], exclude_none: _False) -> Generator[_T, None, None]: ...
def iter_flat_map(*containers, exclude_none: bool = True):
    """iter_flat_cont, but a mapping gives up its values too, not just its
    keys -- `{"a": 1}` yields `"a"` and `1`, pair by pair, instead of only
    `"a"` (plain iteration over a dict, which is all iter_flat_cont does
    with one). Nesting either side, mapping-in-mapping or mapping-in-
    container, recurses the same way; `exclude_none` is iter_flat_cont's.

    A call mixing a mapping and a plain container in one go (or a mapping
    reached only through a container, `[{"a": 1}]`) still works -- it just
    falls through to the second, plainer typing below, since a mapping is
    already a container in its own right. That path cannot see a nested
    mapping's values individually the way the first typing does, only its
    keys, so the precision drops there but nothing is refused.
    """

    for item in containers:
        if is_mapping(item):
            yield from iter_flat_map(*item.items(), exclude_none=exclude_none)
        elif is_container(item):
            yield from iter_flat_map(*item, exclude_none=exclude_none)
        elif not exclude_none or item is not None:
            yield item

@overload
def flat_map(*containers: Mapping[_KT, NestedContainerMappingValue[_KT, Optional[_VT]]], exclude_none: _True = True) -> List[Union[_KT, _VT]]: ...
@overload
def flat_map(*containers: Mapping[_KT, NestedContainerMappingValue[_KT, _VT]], exclude_none: _False) -> List[Union[_KT, _VT]]: ...
@overload
def flat_map(*containers: NestedContainer[Optional[_T]], exclude_none: _True = True) -> List[_T]: ...
@overload
def flat_map(*containers: NestedContainer[_T], exclude_none: _False) -> List[_T]: ...
def flat_map(*containers, exclude_none: bool = True):
    """iter_flat_map, collected into a list."""

    return list(iter_flat_map(*containers, exclude_none=exclude_none))


def iter_flat_cont_by(*containers: Any, is_container: Callable[[Any], bool] = is_container, exclude_none: bool = True) -> Generator[Any, None, None]:
    for item in containers:
        if is_container(item):
            yield from iter_flat_cont_by(*item, is_container=is_container, exclude_none=exclude_none)
        elif not exclude_none or item is not None:
            yield item

def flat_cont_by(*containers: Any, is_container: Callable[[Any], bool] = is_container, exclude_none: bool = True) -> List[Any]:
    return list(iter_flat_cont_by(*containers, is_container=is_container, exclude_none=exclude_none))


@overload
def first_map(func: Callable[[_MT], _T], iterable: Iterable[_MT], /, *, default: _VT = None, predicate: Callable[[_T], bool] = bool) -> Union[_T, _VT]: ...
@overload
def first_map(func: Callable[..., _T], *iterables: Iterable[Any], default: _VT = None, predicate: Callable[[_T], bool] = bool) -> Union[_T, _VT]: ...
def first_map(func: Callable[..., Any], *iterables: Iterable[Any], default: Any = None, predicate: Callable[[Any], bool] = bool):
    """map(func, *iterables), but stops at the first result `predicate`
    accepts and returns it right away, instead of running every item
    through func first -- func is never called past that point, so an
    expensive func or an infinite iterable is fine as long as a hit comes
    early enough.

    `predicate` defaults to `bool`, so the first truthy result wins (0,
    "", [], None, False all fail it) -- pass a stricter one (e.g.
    `lambda x: x is not None`) when a falsy-but-valid result should count.

    Returns `default` (None unless given) once every iterable is
    exhausted without a hit. The single-iterable form types `func`'s
    argument from that iterable's element type, same as `map()` itself;
    calling with more than one iterable falls back to the looser
    `Callable[..., _T]` shape, since matching each iterable to its own
    positional argument that way needs a separate overload per arity.
    """

    for result in map(func, *iterables):
        if predicate(result):
            return result
    return default


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
    "iter_flat_map",
    "flat_map",
    "first_map",
    "pad_list",
    "dedupe",

)
