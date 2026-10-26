"""Rebuilding a container as its own type, its items transformed; behind `data_tools`' walks and `models`' enum conversion."""

from __future__ import annotations as _annotations

import copy
import logging
from collections import deque
from collections.abc import Callable, Hashable, Iterator, Mapping, MutableMapping, Sized
from typing import TYPE_CHECKING, Any, Final, TypeVar, cast

if TYPE_CHECKING:
    from ..typings import Container

_R = TypeVar("_R")
"""A transform's result type."""

_RK = TypeVar("_RK", bound=Hashable)
"""A key transform's result type; hashable, since it becomes a key."""

_MESS: Final = object()
"""Returned by a transform to drop an item; distinct from `None`, which may be kept."""

log = logging.getLogger(__name__)


def _transform(data: Container[Any], func: Callable[[Any], Any] | None = None) -> Iterator[Any]:
    """Yield `data`'s items through `func`, dropping any `_MESS`, lazily.

    An iterator is rebuilt as this directly; every other container has it
    materialised once by `_reconstruct`, so the transform runs one pass.

    Args:
        data: The container to walk.
        func: The transform; `None` keeps items as they are.

    Yields:
        Each transformed item that was not dropped.
    """
    for item in data:
        result = item if func is None else func(item)

        if result is not _MESS:
            yield result


def _transform_mapping(
    data: Mapping[Any, Any],
    key_func: Callable[[Any], Any] | None = None,
    value_func: Callable[[Any], Any] | None = None,
) -> Iterator[tuple[Any, Any]]:
    """Yield `data`'s pairs, each side through its own function.

    A `_MESS` from either side drops the pair; the key is judged first, so a
    dropped pair never pays for its value's transform.

    Args:
        data: The mapping to walk.
        key_func: Transforms keys; `None` keeps them.
        value_func: Transforms values; `None` keeps them.

    Yields:
        Each `(key, value)` pair that was not dropped.
    """
    for raw_key, raw_value in data.items():
        key = raw_key if key_func is None else key_func(raw_key)

        if key is _MESS:
            continue

        value = raw_value if value_func is None else value_func(raw_value)

        if value is _MESS:
            continue

        yield key, value


def _filled(items: Sized, new: Any) -> bool:
    """Tell whether a rebuilt container or mapping really received its items.

    Some constructors accept the wrong argument silently and return an empty
    container (a `dict` subclass whose `__init__` takes a name). Only total
    loss is detected; a legitimate shrink such as set deduplication is not.

    Args:
        items: The transformed items or pairs, already materialised.
        new: The rebuilt container.

    Returns:
        `False` only when `new` is empty although `items` is not.
    """
    try:
        return bool(len(new)) or not items
    except TypeError:
        return True


def _refilled(data: Any, items: Any) -> Any | None:
    """Copy `data`, clear the copy and refill it from `items`.

    `copy.copy` carries over whatever the instance was built with (a name, a
    factory). A copy of a different class is refused, because
    `WeakValueDictionary.__copy__` returns the base class for a subclass.

    Args:
        data: The original container.
        items: What to fill the copy with.

    Returns:
        The refilled copy, or `None` when the copy is not possible.
    """
    try:
        new = copy.copy(data)
    except Exception:
        return None

    if type(new) is not type(data):
        return None

    clear = getattr(new, "clear", None)
    fill = getattr(new, "extend", None) or getattr(new, "update", None)

    if clear is None or fill is None:
        return None

    try:
        clear()
        fill(items)
    except Exception:
        return None

    return new


def _reconstruct(data: Container[Any], func: Callable[[Any], Any] | None = None) -> Container[Any]:
    """Rebuild a container as its own type, every item passed through `func`.

    In order: an iterator is returned as the lazy transform, which shares its
    source and runs `func` only as it is consumed; a namedtuple uses `_make`;
    an `array.array` gets its typecode first; then `cls(items)` (with the
    `maxlen` of a `deque`), checked by `_filled`; then copy-and-refill. When
    nothing works `data` comes back untransformed with a warning, rather than
    as a list the caller cannot use as the type they had. Whatever `func`
    raises propagates.

    Args:
        data: The container to rebuild.
        func: The transform; `None` keeps items as they are.

    Returns:
        The rebuilt container, a lazy iterator, or `data` itself.
    """
    # Any container class may arrive; its constructor is probed below, not known.
    cls = cast("Callable[..., Container[Any]]", type(data))

    if hasattr(cls, "__next__"):
        return _transform(data, func)

    # Materialised before any constructor is probed: a `TypeError` from `func` must
    # propagate, not be mistaken for a constructor refusing the items.
    items = list(_transform(data, func))
    make = getattr(cls, "_make", None)

    if isinstance(data, tuple) and callable(make) and hasattr(data, "_fields"):
        try:
            return make(items)
        except TypeError:
            pass  # A dropped item cannot shrink a namedtuple, and nothing else can hold it.

    if (typecode := getattr(data, "typecode", None)) is not None:
        try:
            return cls(typecode, items)
        except (TypeError, ValueError, OverflowError):
            pass

    try:
        # A `deque` keeps its `maxlen`, which `cls(items)` alone would drop.
        new = cls(items, data.maxlen) if isinstance(data, deque) else cls(items)
    except (TypeError, ValueError, OverflowError):
        pass
    else:
        if _filled(items, new):
            return new

    if (new := _refilled(data, items)) is not None:
        return new

    log.warning(
        "%s could not be rebuilt after the transform, so it is returned as it was, un-transformed",
        type(data).__name__,
    )
    return data


def _reconstruct_mapping(
    data: Mapping[Any, Any],
    key_func: Callable[[Any], Any] | None = None,
    value_func: Callable[[Any], Any] | None = None,
) -> Mapping[Any, Any]:
    """Rebuild a mapping as its own type, both sides transformed.

    The pairs are folded into a dict first, which `Counter`, `ChainMap` and
    `mappingproxy` all need. A `default_factory` is restored before the
    contents, then `cls(as_dict)` and copy-and-refill are tried. A mapping
    that survives none of that comes back as a plain dict, silently: every
    mapping is read by key, so a dict loses only behaviour layered on top.

    Args:
        data: The mapping to rebuild.
        key_func: Transforms keys; `None` keeps them.
        value_func: Transforms values; `None` keeps them.

    Returns:
        The rebuilt mapping, or a plain dict of the transformed pairs.
    """
    # Any mapping class may arrive; its constructor is probed below, not known.
    cls = cast("Callable[..., Mapping[Any, Any]]", type(data))
    as_dict = dict(_transform_mapping(data, key_func, value_func))
    factory = getattr(data, "default_factory", None)

    if callable(factory):
        try:
            new = cls(factory)
            # A mapping with a `default_factory` is taken as `defaultdict`-like, so mutable;
            # one whose `update` refuses falls through to the next attempt below.
            cast("MutableMapping[Any, Any]", new).update(as_dict)
        except (TypeError, ValueError):
            pass
        else:
            if _filled(as_dict, new):
                return new

    try:
        new = cls(as_dict)
    except (TypeError, ValueError):
        pass
    else:
        if _filled(as_dict, new):
            return new

    new = _refilled(data, as_dict)

    if new is not None and _filled(as_dict, new):
        return new

    return as_dict


__all__ = (
    "_filled",
    "_reconstruct",
    "_reconstruct_mapping",
    "_refilled",
    "_transform",
    "_transform_mapping",
    "_MESS",
    "_R",
    "_RK",
)
