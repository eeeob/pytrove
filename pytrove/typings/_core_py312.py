"""Generic type aliases using PEP 695 `type X[T] = ...` syntax.

Only ever imported on Python >= 3.12 (see core.py's version check) -- this
syntax is a hard SyntaxError on older interpreters, so this module must
never be imported unconditionally.
"""

from typing import (
    Collection, Iterator, Reversible,
    Sequence, AbstractSet, Any, Dict, 
    Callable, Coroutine, Awaitable, List, 
    Mapping, 
)


type ContainerWithoutMapping[I] = (
    Sequence[I] |
    AbstractSet[I] |
    Collection[I] |
    Reversible[I] |
    Iterator[I]
)
type Container[I] = (
    Sequence[I] |
    AbstractSet[I] |
    Collection[I] |
    Reversible[I] |
    Iterator[I]
)


type MaybeList[I] = List[I] | I
type MaybeContainer[I] = Container[I] | I
type NestedContainer[I] = Container[NestedContainer[I]] | I
type NestedStrKeyDict[V] = Dict[str, NestedStrKeyDict[V] | V]


type NestedContainerMappingValue[K, V] = (
    Mapping[K, NestedContainerMappingValue[K, V]]
    | ContainerWithoutMapping[NestedContainerMappingValue[K, V]]
    | V
)

type MaybeCoroutine[R] = Coroutine[Any, Any, R] | R
type MaybeCoroutineCallable[**P, R] = Callable[P, MaybeCoroutine[R]]
type MaybeAwaitableCallable[**P, R] = Callable[P, R | Awaitable[R]]
type MaybeAwaitable[**P, R] = MaybeCoroutineCallable[P, R] |  Awaitable[R]


__all__ = (
    "Container",
    "ContainerWithoutMapping",
    "MaybeContainer",
    "NestedContainer",
    "NestedStrKeyDict",
    "MaybeCoroutine",
    "MaybeCoroutineCallable",
    "MaybeAwaitableCallable",
    "MaybeAwaitable",
    "MaybeList", 
    "NestedContainerMappingValue", 
    
)
