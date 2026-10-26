"""Recursive transforms over nested containers and mappings, keeping their shape."""

from __future__ import annotations as _annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, cast, overload

from ..errors import ValidationError
from ..iter_tools import iter_flat_cont
from ..validate_tools import is_container, is_mapping
from ._internal import _none_cleaner, _reconstruct, _reconstruct_mapping, _R, _RK

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from ..typings import (
        Container,
        NestedContainer,
        NestedContainerMappingValue,
        _EnumT,
        _KT,
        _T,
        _VT,
    )


@overload
def map_deep(
    data: Mapping[_KT, NestedContainerMappingValue[_KT, _VT]],
    func: Callable[[_KT | _VT], _RK],
) -> Mapping[_RK, NestedContainerMappingValue[_RK, _RK]]: ...
@overload
def map_deep(data: NestedContainer[_T], func: Callable[[_T], _R]) -> NestedContainer[_R]: ...
def map_deep(data: Any, func: Callable[[Any], Any]) -> Any:
    """Apply `func` to every leaf under `data`, mapping keys included, keeping the shape.

    Containers and mappings are rebuilt as their own type where possible; a
    container that cannot be rebuilt comes back untransformed with a warning,
    and a mapping falls back to a plain dict. Keys that transform to equal
    values collapse into one, the last winning. Whatever `func` raises
    propagates; under an iterator, which comes back as a lazy iterator over
    the same source, that happens only as the result is consumed.

    Args:
        data: A leaf, or a container or mapping of them, at any depth.
        func: Called on each leaf; it never sees a container or mapping.

    Returns:
        The transformed structure, or `func(data)` for a bare leaf.

    Example:
        >>> map_deep({"a": [1, (2,)]}, lambda v: v * 2)
        {'aa': [2, (4,)]}
    """
    return map_deep_kv(data, func, func)


@overload
def map_deep_kv(
    data: Mapping[_KT, NestedContainerMappingValue[_KT, _VT]],
    value_func: Callable[[_VT], _R],
    key_func: Callable[[_KT], _RK],
) -> Mapping[_RK, NestedContainerMappingValue[_RK, _R]]: ...
@overload
def map_deep_kv(
    data: Mapping[_KT, NestedContainerMappingValue[_KT, _VT]],
    value_func: Callable[[_VT], _R],
    key_func: None = None,
) -> Mapping[_KT, NestedContainerMappingValue[_KT, _R]]: ...
@overload
def map_deep_kv(
    data: NestedContainer[_T],
    value_func: Callable[[_T], _R],
    key_func: Callable[[Any], Any] | None = None,
) -> NestedContainer[_R]: ...
def map_deep_kv(
    data: Any, value_func: Callable[[Any], Any], key_func: Callable[[Any], Any] | None = None
) -> Any:
    """Apply `map_deep` with separate functions for mapping keys and everything else.

    `key_func` sees only a key that is itself a leaf; a key that is a
    container (a tuple) is walked like any value, its leaves passed to
    `value_func`. Values of every shape recurse back through this function,
    and an iterator comes back lazy, as with `map_deep`.

    Args:
        data: A leaf, or a container or mapping of them, at any depth.
        value_func: Called on every leaf that is not a leaf key.
        key_func: Called on each leaf key; `None` leaves keys unchanged.

    Returns:
        The transformed structure, or `value_func(data)` for a bare leaf.

    Example:
        >>> map_deep_kv({"a": [1, 2]}, lambda v: v * 10, str.upper)
        {'A': [10, 20]}
    """

    def key_step(key: Any) -> Any:
        """Transform one key.

        Args:
            key: A mapping key.

        Returns:
            It, transformed.
        """
        if is_container(key):
            return value_step(key)

        return key_func(key) if key_func is not None else key

    def value_step(value: Any) -> Any:
        """Recurse into one value or container item.

        Args:
            value: A value or item.

        Returns:
            It, transformed.
        """
        return map_deep_kv(value, value_func, key_func)

    if is_mapping(data):
        return _reconstruct_mapping(data, key_step, value_step)

    if is_container(data):
        return _reconstruct(data, value_step)

    return value_func(data)


def snapshot(data: _T) -> _T:
    """Copy a structure so the copy shares nothing mutable with it.

    The exception is an iterator, which cannot be copied without consuming it:
    it comes back as a lazy iterator over the same source, so consuming either
    one drains the other.

    Args:
        data: A leaf, or a container or mapping of them, at any depth.

    Returns:
        An equal structure of the same shape, every container and mapping rebuilt.
    """
    # `map_deep` keeps the shape, which its overloads cannot carry from `_T` to `_T`.
    return cast("_T", map_deep(data, lambda value: value))


def enum_to_value(data: Any) -> Any:
    """Replace every enum member, keys included, with its `.value`, ready for JSON.

    Args:
        data: A leaf, or a container or mapping of them, at any depth.

    Returns:
        The structure with enum members replaced by their values.

    Example:
        >>> class Color(Enum):
        ...     RED = 1
        >>> enum_to_value({Color.RED: [Color.RED, "x"]})
        {1: [1, 'x']}
    """
    # Typed `Any`: the shape survives, but each member turns into its value's type.
    return map_deep(data, lambda value: value.value if isinstance(value, Enum) else value)


@overload
def value_to_enum(
    values: Mapping[_KT, _VT],
    enum_classes: NestedContainer[type[_EnumT]],
    map_resolve_type: Literal["k", "K"],
) -> Mapping[_KT | _EnumT, _VT]: ...
@overload
def value_to_enum(
    values: Mapping[_KT, _VT],
    enum_classes: NestedContainer[type[_EnumT]],
    map_resolve_type: Literal["v", "V"] = "v",
) -> Mapping[_KT, _EnumT | _VT]: ...
@overload
def value_to_enum(
    values: Container[_T],
    enum_classes: NestedContainer[type[_EnumT]],
    map_resolve_type: Literal["k", "K", "v", "V"] = "v",
) -> Container[_EnumT | _T]: ...
@overload
def value_to_enum(
    values: _T,
    enum_classes: NestedContainer[type[_EnumT]],
    map_resolve_type: Literal["k", "K", "v", "V"] = "v",
) -> _EnumT | _T: ...
def value_to_enum(
    values: Any, enum_classes: NestedContainer[type[Enum]], map_resolve_type: str = "v"
) -> Any:
    """Replace raw values with the enum member that has that value, recursively.

    Values with no matching member, unhashable ones included, pass through.
    On a value collision the later class wins, and ordinary data equal to a
    member's value converts too.

    `"v"` converts every leaf except mapping keys. `"k"` converts mapping keys
    only, a tuple key's items included, at any depth: every other leaf stays,
    though containers and mapping values are still walked to reach the keys
    of nested mappings.

    Args:
        values: A leaf, or a container or mapping of them, at any depth.
        enum_classes: The enum classes to look values up in.
        map_resolve_type: `"v"` or `"k"`, in either case: the side to convert.

    Returns:
        The structure with matching values replaced by members.

    Raises:
        ValidationError: If `map_resolve_type` is not `"k"` or `"v"`.

    Example:
        >>> class Color(Enum):
        ...     RED = 1
        >>> value_to_enum({"c": [1, 2]}, Color)
        {'c': [<Color.RED: 1>, 2]}
        >>> value_to_enum({1: "x"}, Color, "k")
        {<Color.RED: 1>: 'x'}
    """
    if not isinstance(map_resolve_type, str) or map_resolve_type.lower() not in ("v", "k"):
        msg = f"map_resolve_type must be k or v not {map_resolve_type!r}"
        raise ValidationError(msg)

    keys = map_resolve_type.lower() == "k"

    enum_map: dict[Any, Enum] = {}

    # `ty` binds `_T` to the container arm of the recursive `NestedContainer[_T]`, so
    # it cannot recover the leaf type (astral-sh/ty#1703); the parameter states it.
    classes = cast("Iterator[type[Enum]]", iter_flat_cont(enum_classes))

    # In argument order, so that on a collision the class passed last wins.
    for enum_cls in classes:
        enum_map.update(enum_cls._value2member_map_)

    def lookup(v: Any) -> Any:
        """Convert one leaf.

        Args:
            v: The leaf.

        Returns:
            Its member, or it unchanged.
        """
        try:
            return enum_map.get(v, v)
        except TypeError:  # Unhashable, so no member's value.
            return v

    def walk(v: Any) -> Any:
        """Convert the chosen side under one value, recursing into containers and mappings.

        Args:
            v: The value.

        Returns:
            It, converted.
        """
        if is_mapping(v):
            key_func = (lambda key: map_deep(key, lookup)) if keys else None
            return _reconstruct_mapping(v, key_func, walk)

        if is_container(v):
            return _reconstruct(v, walk)

        return v if keys else lookup(v)

    return walk(values)


def clean_none_values(data: _T) -> _T:
    """Remove every `None`, recursively, keeping the shape.

    A mapping loses each entry whose value is `None` (keys are never judged);
    a container loses the item. An entry left empty is kept. A namedtuple that
    would lose a field comes back whole, `None` included, with a warning. An
    iterator comes back as a lazy iterator over the same source.

    Args:
        data: A container or mapping, at any depth; anything else is returned as is.

    Returns:
        The structure without `None`s.

    Example:
        >>> clean_none_values({"a": None, "b": [1, None, {"c": None}]})
        {'b': [1, {}]}
    """
    # The cleaner rebuilds `data` as its own type, which its signature cannot carry to `_T`.
    return data if data is None else cast("_T", _none_cleaner(data))


def clean_none_kw(**kwargs: Any) -> dict[str, Any]:
    """Drop keyword arguments left at `None`, to forward optional arguments.

    `client.request(**clean_none_kw(limit=limit))` lets the callee use its own default.

    Args:
        **kwargs: The arguments.

    Returns:
        The arguments without `None` values, nested values cleaned too.

    Example:
        >>> clean_none_kw(limit=None, offset=3)
        {'offset': 3}
    """
    return clean_none_values(kwargs)


__all__ = (
    "snapshot",
    "map_deep",
    "map_deep_kv",
    "enum_to_value",
    "clean_none_values",
    "value_to_enum",
    "clean_none_kw",
)
