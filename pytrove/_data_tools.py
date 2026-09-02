from typing import Any, Callable, Iterator, Mapping, Optional, Tuple

import copy
import logging

from .typings import Container

log = logging.getLogger(__name__)

#: Sentinel meaning "drop this item" -- distinct from None, which a caller may
#: legitimately want kept.
_MESS = object()


def _transform(data: Container, func: Optional[Callable] = None) -> Iterator:
    """Yield `data`'s items through `func`, dropping any _MESS. Lazy: a fresh
    one of these is handed to each reconstruction attempt below rather than
    materialised once, so the common case pays for exactly one pass."""

    for item in data:
        if func is not None:
            item = func(item)

        if item is not _MESS:
            yield item

def _transform_mapping(data: Mapping, key_func: Optional[Callable] = None, value_func: Optional[Callable] = None) -> Iterator[Tuple[Any, Any]]:
    """Yield `data`'s pairs, each side through its own function. A _MESS from
    either side drops the whole pair; the key is judged first so a pair that
    is going anyway never pays for a value transform that gets discarded."""

    for key, value in data.items():
        if key_func is not None:
            key = key_func(key)

        if key is _MESS:
            continue

        if value_func is not None:
            value = value_func(value)

        if value is _MESS:
            continue

        yield key, value


def _filled(data: Container, func: Optional[Callable], new: Any) -> bool:
    """Whether `new` actually received the items it was built from.

    Some constructors accept the wrong argument without complaining (a
    `class Cfg(dict)` whose __init__ takes a name, this package's own
    KeyDefaultDict taking it as `default_factory`) and hand back an empty
    container instead of raising. That total loss is the one failure worth
    detecting; a legitimate shrink (a set deduplicating) is not, so only
    emptiness is checked, and only re-walks `data` when `new` actually came
    back empty. A type with no __len__ is taken at its word.
    """

    try:
        if len(new):
            return True
    except TypeError:
        return True

    return next(_transform(data, func), _MESS) is _MESS


def _mapping_filled(as_dict: dict, new: Any) -> bool:
    """_filled's mapping counterpart. `as_dict` is already materialised (that
    materialisation is the fix for Counter/ChainMap/mappingproxy, not an
    expense to avoid -- see _reconstruct_mapping), so this only checks
    emptiness against it rather than an exact length."""

    return bool(new) or not as_dict


def _refilled(data: Any, items: Any) -> Optional[Any]:
    """A copy of `data`, cleared and refilled from `items`, or None.

    The last resort before the type is given up on: copy.copy carries across
    whatever the instance was built with (a name, a schema, a factory), and
    clear()+extend()/update() puts the new contents in its place.

    None comes back whenever the copy is not the same class as the original
    -- weakref.WeakValueDictionary.__copy__ hardcodes the base class, so
    copying a subclass of it would otherwise quietly trade the type away.
    """

    try:
        new = copy.copy(data)
    except Exception:
        return

    if type(new) is not type(data):
        return

    clear = getattr(new, "clear", None)
    fill = getattr(new, "extend", None) or getattr(new, "update", None)

    if clear is None or fill is None:
        return

    try:
        clear()
        fill(items)
    except Exception:
        return

    return new


def _reconstruct(data: Container, func: Optional[Callable] = None) -> Container:
    """Rebuild `data` as its own type, every item passed through `func`.

    `type(data)(items)` is the goal, and is exactly what happens for a list,
    tuple, set, frozenset, deque or ordinary subclass of those. The rest is
    the types where that line is wrong:

    - An iterator (generator/map/zip/enumerate/reversed) is not rebuilt at
      all -- `zip(items)`/`enumerate(items)` both "succeed" with the wrong
      answer -- the lazy transform is returned instead.
    - A namedtuple goes through `_make` (found by duck-typing `_make`/
      `_fields`, not by isinstance), since `Point(items)` is a missing-
      argument TypeError.
    - A typecode carrier (array.array) gets its typecode read back and
      passed first.
    - Then the general `cls(items)`, checked by _filled rather than trusted.
    - Then copy-and-refill (_refilled), for a subclass whose __init__ takes
      arguments this cannot guess.

    When none of that works, `data` is returned untouched -- un-transformed
    -- with a warning naming the type, rather than silently substituting a
    list a caller could not use as the range/view/etc. they asked for. A
    mapping falls back to dict instead; see _reconstruct_mapping.
    """

    cls = type(data)

    if hasattr(cls, "__next__"):
        return _transform(data, func)

    # Each attempt below takes its own fresh _transform(data, func) rather
    # than a shared list: the first attempt is the only one an ordinary type
    # ever reaches.

    if isinstance(data, tuple) and hasattr(cls, "_make") and hasattr(data, "_fields"):
        try:
            return cls._make(_transform(data, func))
        except TypeError:
            pass  # a dropped item can't shrink a namedtuple; nothing else can hold it either

    if (typecode := getattr(data, "typecode", None)) is not None:
        try:
            return cls(typecode, _transform(data, func))
        except (TypeError, ValueError):
            pass

    try:
        new = cls(_transform(data, func))
    except (TypeError, ValueError):
        pass
    else:
        if _filled(data, func, new):
            return new

    if (new := _refilled(data, _transform(data, func))) is not None:
        return new

    log.warning(
        "%s could not be rebuilt after the transform, so it is returned as it was, "
        "un-transformed", type(data).__name__
    )

    return data


def _reconstruct_mapping(data: Mapping, key_func: Optional[Callable] = None, value_func: Optional[Callable] = None) -> Mapping:
    """Rebuild `data` as its own mapping type, both sides transformed.

    The pairs are folded through dict() first -- unlike _reconstruct, this
    materialisation is required, not optional: Counter(pairs) counts the
    pairs as elements, ChainMap(pairs) takes the iterator as one of its
    *maps*, and mappingproxy(pairs) refuses outright. A real dict fixes all
    three at once, and is built once and reused for every attempt below.

    A `default_factory` is restored before the contents -- defaultdict and
    this package's KeyDefault* dicts take it in the argument position the
    contents would otherwise go in, and KeyDefaultDict does not even raise
    on the mistake, it just comes back empty. Then the general `cls(as_dict)`
    and copy-and-refill (_refilled), both checked by _mapping_filled.

    A mapping that survives none of that comes back as a plain dict, with
    its contents converted -- silently, unlike _reconstruct's warning. Every
    mapping here is read by key, so a dict answers `[...]`, `.get`, `.items`,
    `in`, iteration and json.dumps the same way; what is lost is only
    behaviour layered on top (a Counter's arithmetic, a ChainMap's layers).
    A sequence type has no such common denominator, which is why
    _reconstruct's fallback is different.
    """

    cls = type(data)
    as_dict = dict(_transform_mapping(data, key_func, value_func))

    factory = getattr(data, "default_factory", None)

    if callable(factory):
        try:
            new = cls(factory)
            new.update(as_dict)
        except (TypeError, ValueError):
            pass
        else:
            if _mapping_filled(as_dict, new):
                return new

    try:
        new = cls(as_dict)
    except (TypeError, ValueError):
        pass
    else:
        if _mapping_filled(as_dict, new):
            return new

    new = _refilled(data, as_dict)

    if new is not None and _mapping_filled(as_dict, new):
        return new

    return as_dict
