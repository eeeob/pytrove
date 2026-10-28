from __future__ import annotations as _annotations

import inspect
import os
import threading
from collections import UserString
from collections.abc import (
    Awaitable,
    Callable,
    Collection,
    Coroutine,
    Hashable,
    Iterator,
    Mapping,
    Reversible,
    Sequence,
)
from collections.abc import Set as AbstractSet
from enum import Enum
from types import UnionType
from typing import (
    Annotated,
    Any,
    Literal,
    ParamSpec,
    TypeVar,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

import pytest

from pytrove.typings import (
    Container,
    ContainerWithoutMapping,
    CountryInfo,
    JsonValue,
    LockProtocol,
    MaybeAwaitable,
    MaybeAwaitableCallable,
    MaybeContainer,
    MaybeCoroutine,
    MaybeCoroutineCallable,
    MaybeList,
    NestedContainer,
    NestedContainerMappingValue,
    NestedStrKeyDict,
    NotContainer,
    Number,
    PathLike,
    PhoneNumber,
    RegionCode,
    StrInt,
    _CT,
    _EnumT,
    _ExcT,
    _False,
    _FT,
    _KT,
    _P,
    _T,
    _True,
    _VT,
)

CONTAINER_ORIGINS = [Sequence, AbstractSet, Collection, Reversible, Iterator]


def _value(alias: Any) -> Any:
    """Unwrap a PEP 695 alias (3.12+) to the union it stands for."""
    return getattr(alias, "__value__", alias)


@pytest.mark.parametrize("alias", [Container, ContainerWithoutMapping])
def test_container_aliases_keep_the_member_order(alias: Any) -> None:
    assert [get_origin(a) or a for a in get_args(_value(alias))] == CONTAINER_ORIGINS


def test_not_container_lists_the_iterables_read_as_single_values() -> None:
    assert set(get_args(NotContainer)) == {
        bytearray,
        bytes,
        str,
        UserString,
        memoryview,
        type(Enum),
        Awaitable,
    }


def _shape(alias: Any) -> list[Any]:
    """List the member origins of an alias, the same way before and after 3.12.

    A PEP 695 alias is unwrapped through `__value__`, a nested one is expanded in
    place, and every type variable or `ParamSpec` reads as `TypeVar`, so the
    pre-3.12 `TypeAlias` and the 3.12+ `type` statement give the same list.
    """
    value = getattr(alias, "__value__", alias)
    members = get_args(value) if get_origin(value) in (Union, UnionType) else (value,)
    shape: list[Any] = []

    for member in members:
        origin = get_origin(member)
        if hasattr(origin, "__value__"):
            shape += _shape(origin)
        elif isinstance(member, (TypeVar, ParamSpec)):
            shape.append(TypeVar)
        else:
            shape.append(origin or member)

    return shape


@pytest.mark.parametrize(
    ("alias", "shape"),
    [
        (Container, CONTAINER_ORIGINS),
        (ContainerWithoutMapping, CONTAINER_ORIGINS),
        (MaybeList, [list, TypeVar]),
        (MaybeContainer, [*CONTAINER_ORIGINS, TypeVar]),
        (NestedContainer, [*CONTAINER_ORIGINS, TypeVar]),
        (NestedStrKeyDict, [dict]),
        (NestedContainerMappingValue, [Mapping, *CONTAINER_ORIGINS, TypeVar]),
        (JsonValue, [str, bool, int, float, type(None), list, dict]),
        (MaybeCoroutine, [Coroutine, TypeVar]),
        (MaybeCoroutineCallable, [Callable]),
        (MaybeAwaitableCallable, [Callable]),
        (MaybeAwaitable, [Callable, Awaitable]),
    ],
)
def test_each_generic_alias_has_the_same_shape_on_every_version(
    alias: Any, shape: list[Any]
) -> None:
    assert _shape(alias) == shape


@pytest.mark.parametrize(
    "alias", [Container, ContainerWithoutMapping, MaybeList, MaybeContainer, NestedContainer]
)
def test_one_parameter_aliases_take_their_type_argument(alias: Any) -> None:
    # Before 3.12 the argument is substituted into the union; from 3.12 it stays on the alias.
    assert int in get_args(alias[int]) or all(int in get_args(a) for a in get_args(alias[int]))


def test_nested_str_key_dict_has_string_keys() -> None:
    value = getattr(NestedStrKeyDict, "__value__", NestedStrKeyDict)
    assert get_args(value)[0] is str


def test_nested_container_mapping_value_bounds_its_key_to_hashable() -> None:
    key, value = NestedContainerMappingValue.__parameters__
    assert key.__bound__ is Hashable
    assert value.__bound__ is None


@pytest.mark.parametrize(
    ("alias", "metadata"),
    [
        (PhoneNumber, "Phone number in international format, e.g. +967xxxxxxxxx"),
        (RegionCode, "ISO region code, verify that it is valid"),
    ],
)
def test_annotated_string_aliases_carry_their_note(alias: Any, metadata: str) -> None:
    assert get_origin(alias) is Annotated
    assert get_args(alias) == (str, metadata)


def test_number_and_str_int_are_plain_unions() -> None:
    assert set(get_args(Number)) == {int, float}
    assert set(get_args(StrInt)) == {int, str}


def test_json_value_covers_the_json_types() -> None:
    members = [get_origin(a) or a for a in get_args(_value(JsonValue))]
    assert {str, bool, int, float, type(None), list, dict} <= set(members)


def test_path_like_accepts_strings_bytes_and_os_paths() -> None:
    assert set(get_args(PathLike)) == {str, bytes, os.PathLike[str], os.PathLike[bytes]}


def test_type_variables_carry_their_bounds() -> None:
    assert isinstance(_P, ParamSpec)
    bounds = {
        _T: None,
        _VT: None,
        _KT: Hashable,
        _CT: type,
        _FT: Callable[..., Any],
        _ExcT: BaseException,
        _EnumT: Enum,
    }
    for var, bound in bounds.items():
        assert isinstance(var, TypeVar)
        assert var.__bound__ == bound


def test_boolean_literals() -> None:
    assert _True == Literal[True]
    assert _False == Literal[False]


@pytest.mark.parametrize("name", ["acquire", "release"])
def test_lock_protocol_methods_take_no_argument(name: str) -> None:
    assert list(inspect.signature(getattr(LockProtocol, name)).parameters) == ["self"]


def test_a_threading_lock_satisfies_lock_protocol() -> None:
    lock = threading.Lock()
    assert lock.acquire() is True
    assert lock.release() is None


def test_country_info_fields() -> None:
    assert get_type_hints(CountryInfo) == {"cc": int, "rc": str, "flag": str, "name": str}
