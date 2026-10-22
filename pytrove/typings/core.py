"""Type aliases, type variables and protocols general to the whole package.

Types scoped to one feature live in a sibling module named for it (see
`template.py`), because `pytrove.typings` re-exports every module flat.
"""

from __future__ import annotations as _annotations

import os
import sys
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
    Set as AbstractSet,
)
from enum import Enum, EnumMeta as EnumType  # `EnumType` became the name of `EnumMeta` only in 3.11.
from typing import Annotated, Any, Literal, ParamSpec, Protocol, TypeAlias, TypedDict, TypeVar

_P = ParamSpec("_P")
"""The parameters of a wrapped callable."""

_T = TypeVar("_T")
"""Any value type."""

_KT = TypeVar("_KT", bound=Hashable)
"""A mapping key type."""

_VT = TypeVar("_VT")
"""A mapping value type."""

_CT = TypeVar("_CT", bound=type)
"""A class."""

_FT = TypeVar("_FT", bound=Callable[..., Any])
"""A callable, kept with its exact type through a decorator."""

_ExcT = TypeVar("_ExcT", bound=BaseException)
"""An exception type."""

_EnumT = TypeVar("_EnumT", bound=Enum)
"""An enum class."""

_True: TypeAlias = Literal[True]
"""The `True` literal, for `@overload`s that dispatch on a boolean flag."""

_False: TypeAlias = Literal[False]
"""The `False` literal, for `@overload`s that dispatch on a boolean flag."""

if sys.version_info >= (3, 12):
    from ._core_py312 import (
        Container,
        ContainerWithoutMapping,
        JsonValue,
        MaybeAwaitable,
        MaybeAwaitableCallable,
        MaybeContainer,
        MaybeCoroutine,
        MaybeCoroutineCallable,
        MaybeList,
        NestedContainer,
        NestedContainerMappingValue,
        NestedStrKeyDict,
    )
else:
    # يجب المحافظة على ترتيب الاولويات
    ContainerWithoutMapping: TypeAlias = Sequence[_T] | AbstractSet[_T] | Collection[_T] | Reversible[_T] | Iterator[_T]
    """An iterable container that is not read as a mapping."""

    Container: TypeAlias = Sequence[_T] | AbstractSet[_T] | Collection[_T] | Reversible[_T] | Iterator[_T]
    """An iterable container; see `NotContainer` for the iterables that do not count."""

    MaybeList: TypeAlias = list[_T] | _T
    """One value, or a list of them."""

    MaybeContainer: TypeAlias = Container[_T] | _T
    """One value, or a container of them."""

    # The quoted self-reference is the pre-3.12 exception in rule 4.2.
    NestedStrKeyDict: TypeAlias = dict[str, "NestedStrKeyDict[_T]" | _T]  # noqa: TC010 - `TypeVar.__ror__` accepts the `str`
    """A dict with string keys whose values are leaves or further such dicts."""

    NestedContainer: TypeAlias = Container["NestedContainer[_T]"] | _T
    """A leaf, or a container of leaves and further such containers, at any depth."""

    NestedContainerMappingValue: TypeAlias = (
        Mapping[_KT, "NestedContainerMappingValue[_KT, _VT]"]
        | ContainerWithoutMapping["NestedContainerMappingValue[_KT, _VT]"]
        | _VT
    )
    """A leaf, or a mapping or container of further such values, at any depth."""

    JsonValue: TypeAlias = str | bool | int | float | None | list["JsonValue"] | dict[str, "JsonValue"]
    """Any value `json` can represent."""

    MaybeCoroutine: TypeAlias = Coroutine[Any, Any, _T] | _T
    """A value, or a coroutine resolving to it."""

    MaybeCoroutineCallable: TypeAlias = Callable[_P, MaybeCoroutine[_T]]
    """A plain function or a coroutine function."""

    MaybeAwaitableCallable: TypeAlias = Callable[_P, _T | Awaitable[_T]]
    """A callable whose result may or may not need awaiting."""

    MaybeAwaitable: TypeAlias = MaybeCoroutineCallable[_P, _T] | Awaitable[_T]
    """A callable to run, or an awaitable already created."""

NotContainer: TypeAlias = bytearray | bytes | str | memoryview | EnumType | Awaitable
"""Iterables that are treated as single values rather than containers."""

PhoneNumber: TypeAlias = Annotated[str, "Phone number in international format, e.g. +967xxxxxxxxx"]
"""A phone number in international format."""

RegionCode: TypeAlias = Annotated[str, "ISO region code, verify that it is valid"]
"""A two-letter ISO 3166 region code."""

Number: TypeAlias = int | float
"""An integer or a float."""

StrInt: TypeAlias = int | str
"""An integer or its string form."""

PathLike: TypeAlias = str | bytes | os.PathLike[str] | os.PathLike[bytes]
"""Anything `open` and `os` accept as a path."""


class LockProtocol(Protocol):
    """A lock the file tools can hold around a read or write, such as `threading.Lock`."""

    def acquire(self) -> bool:
        """Acquire the lock, blocking until it is free.

        Returns:
            Whether the lock was acquired.
        """
        ...

    def release(self) -> Any:
        """Release the lock.

        Returns:
            Whatever the lock's own `release` returns; it is ignored.
        """
        ...


class CountryInfo(TypedDict):
    """One country, as `country_tools.get_cinfo` returns it."""

    cc: int
    """The international calling code, such as `966`."""

    rc: str
    """The ISO 3166 region code, such as `"SA"`."""

    flag: str
    """The flag emoji."""

    name: str
    """The English name."""


__all__ = (
    "Container",
    "NestedContainer",
    "NotContainer",
    "ContainerWithoutMapping",
    "PhoneNumber",
    "NestedStrKeyDict",
    "RegionCode",
    "MaybeAwaitable",
    "CountryInfo",
    "Number",
    "StrInt",
    "MaybeCoroutineCallable",
    "MaybeContainer",
    "JsonValue",
    "PathLike",
    "LockProtocol",
    "MaybeAwaitableCallable",
    "MaybeCoroutine",
    "MaybeList",
    "NestedContainerMappingValue",
    "_P",
    "_T",
    "_CT",
    "_FT",
    "_KT",
    "_VT",
    "_True",
    "_False",
    "_EnumT",
    "_ExcT",
)
