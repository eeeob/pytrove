"""The package-wide type aliases, TypeVars and protocols.

Everything here is general to pytrove as a whole -- anything scoped to one
feature lives in its own sibling module (see template.py) and is named for
that scope, since the whole package is re-exported flat from
pytrove.typings.
"""

from typing import (
    Collection, Union, Reversible, Iterator, 
    Sequence, AbstractSet, TypeAlias, 
    Any, Dict, Annotated, Callable, Coroutine, 
    Awaitable, ParamSpec, TypeVar, Literal, 
    TypedDict, Hashable, Protocol, List, Mapping
    
)

from enum import EnumMeta as EnumType, Enum  # EnumType is only an alias for EnumMeta added in 3.11

import sys
import os


class LockProtocol(Protocol):
    def acquire(self) -> bool: ...
    def release(self) -> Any: ...


_P = ParamSpec("_P")
_T = TypeVar("_T")
_KT = TypeVar("_KT", bound=Hashable)
_VT = TypeVar("_VT")


if sys.version_info >= (3, 12):
    from ._core_py312 import *
else:
    #يجب المحافظة على ترتيب الاولويات
    ContainerWithoutMapping: TypeAlias = Union[
        Sequence[_T], 
        AbstractSet[_T], 
        Collection[_T], 
        Reversible[_T], 
        Iterator[_T], 
    ]
    Container: TypeAlias = ContainerWithoutMapping[_T] #تحققت مؤخرا ان Mapping يرث من Collection

    
    MaybeList: TypeAlias = Union[List[_T], _T]
    MaybeContainer: TypeAlias = Union[Container[_T], _T]
    NestedStrKeyDict: TypeAlias = Dict[str, Union["NestedStrKeyDict[_T]", _T]]
    NestedContainer: TypeAlias = Union[Container["NestedContainer[_T]"], _T]

    NestedContainerMappingValue: TypeAlias = Union[
        "NestedContainerMapping[_KT, _VT]", 
        ContainerWithoutMapping["NestedContainerMappingValue[_KT, _VT]"], 
        _VT
    ]
    NestedContainerMapping: TypeAlias = Mapping[
        NestedContainer[_KT],
        NestedContainerMappingValue[_KT, _VT],
    ]
    

    MaybeCoroutine: TypeAlias = Union[Coroutine[Any, Any, _T], _T]
    MaybeCoroutineCallable: TypeAlias = Callable[_P, MaybeCoroutine[_T]]
    MaybeAwaitableCallable: TypeAlias = Callable[_P, Union[_T, Awaitable[_T]]]
    MaybeAwaitable: TypeAlias = Union[MaybeCoroutineCallable[_P, _T], Awaitable[_T]]
    


JsonValue: TypeAlias = Union[
    str, bool, int, float, None,
    List['JsonValue'],
    Dict[str, 'JsonValue'],
    ]

NotContainer: TypeAlias = Union[bytearray, bytes, str, memoryview, EnumType, Awaitable]
PhoneNumber: TypeAlias = Annotated[str, "Phone number in international format, e.g. +967xxxxxxxxx"]
RegionCode: TypeAlias = Annotated[str, "ISO region code, verify that it is valid"]
Number: TypeAlias = Union[int, float]
StrInt: TypeAlias = Union[int, str]
PathLike: TypeAlias = Union[str, bytes, "os.PathLike[str]", "os.PathLike[bytes]"]


_CT = TypeVar("_CT", bound=type)
_FT = TypeVar("_FT", bound=Callable[..., Any])
_ExcT = TypeVar("_ExcT", bound=BaseException)
_EnumT = TypeVar("_EnumT", bound=Enum)

_True: TypeAlias = Literal[True]
_False: TypeAlias = Literal[False]


class CountryInfo(TypedDict):
    cc: int
    rc: str
    flag: str
    name: str



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
    "NestedContainerMapping", 
    "_P", "_T", "_CT", "_FT",
    "_KT", "_VT", "_True", "_False",
    "_EnumT", "_ExcT", 


)
