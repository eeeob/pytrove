"""The recursive and generic aliases of `core`, as PEP 695 `type` statements.

Imported only on Python 3.12 and later: the syntax is a `SyntaxError` on
older interpreters, which use the `TypeAlias` versions in `core` instead.
"""

from __future__ import annotations as _annotations

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
from typing import Any

type ContainerWithoutMapping[I] = (
    Sequence[I] | AbstractSet[I] | Collection[I] | Reversible[I] | Iterator[I]
)
"""The same union as `Container`, under a name that records the intent.

Nothing in the type excludes a mapping (`Collection` covers `Mapping` too); the
name only documents that the value is meant to be read as items, not as pairs.
"""

type Container[I] = Sequence[I] | AbstractSet[I] | Collection[I] | Reversible[I] | Iterator[I]
"""An iterable container; see `NotContainer` for the iterables that do not count."""

type MaybeList[I] = list[I] | I
"""One value, or a list of them."""

type MaybeContainer[I] = Container[I] | I
"""One value, or a container of them."""

type NestedContainer[I] = Container[NestedContainer[I]] | I
"""A leaf, or a container of leaves and further such containers, at any depth."""

type NestedStrKeyDict[V] = dict[str, NestedStrKeyDict[V] | V]
"""A dict with string keys whose values are leaves or further such dicts."""

type NestedContainerMappingValue[K: Hashable, V] = (
    Mapping[K, NestedContainerMappingValue[K, V]]
    | ContainerWithoutMapping[NestedContainerMappingValue[K, V]]
    | V
)
"""A leaf, or a mapping or container of further such values, at any depth."""

type JsonValue = str | bool | int | float | None | list[JsonValue] | dict[str, JsonValue]
"""Any value `json` can represent."""

type MaybeCoroutine[R] = Coroutine[Any, Any, R] | R
"""A value, or a coroutine resolving to it."""

type MaybeCoroutineCallable[**P, R] = Callable[P, MaybeCoroutine[R]]
"""A plain function or a coroutine function."""

type MaybeAwaitableCallable[**P, R] = Callable[P, R | Awaitable[R]]
"""A callable whose result may or may not need awaiting."""

type MaybeAwaitable[**P, R] = MaybeCoroutineCallable[P, R] | Awaitable[R]
"""A callable to run, or an awaitable already created."""

__all__ = (
    "Container",
    "ContainerWithoutMapping",
    "JsonValue",
    "MaybeAwaitable",
    "MaybeAwaitableCallable",
    "MaybeContainer",
    "MaybeCoroutine",
    "MaybeCoroutineCallable",
    "MaybeList",
    "NestedContainer",
    "NestedContainerMappingValue",
    "NestedStrKeyDict",
)
