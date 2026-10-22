"""Helpers private to `callable_tools`: the protocols that spell decorator return types."""

from __future__ import annotations as _annotations

from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, Protocol, TypeAlias, TypeVar, overload

from ..typings import _False, _P, _T, _True, _VT

_Coro: TypeAlias = Coroutine[Any, Any, _T]
"""A coroutine resolving to `_T`."""

_ET_co = TypeVar("_ET_co", covariant=True)
"""`middleware`'s `on_error` result type; covariant, since it only ever appears as a return."""

_AT_co = TypeVar("_AT_co", covariant=True)
"""`middleware`'s `after` result type; covariant for the same reason."""

_T_contra = TypeVar("_T_contra", contravariant=True)
"""The wrapped function's result type, where a protocol only ever takes it in."""

_T_co = TypeVar("_T_co", covariant=True)
"""A result type a protocol only ever hands back."""

_ExcLogger: TypeAlias = bool | Callable[[BaseException], Any]
"""`safe_call`'s `log_exc`: `True` to log, or a callback receiving the exception."""


class _WaitOnErrorDecorator(Protocol[_P, _ET_co]):
    """What `middleware(on_error=...)` returns for a sync `on_error`."""

    @overload
    def __call__(self, func: Callable[_P, _Coro[_T]]) -> Callable[_P, _Coro[_T | _ET_co]]: ...
    @overload
    def __call__(self, func: Callable[_P, _T]) -> Callable[_P, _T | _ET_co]: ...


class _AwaitOnErrorDecorator(Protocol[_P, _ET_co]):
    """What `middleware(on_error=...)` returns for an async `on_error`."""

    @overload
    def __call__(self, func: Callable[_P, _Coro[_T]]) -> Callable[_P, _Coro[_T | _ET_co]]: ...
    @overload
    def __call__(self, func: Callable[_P, _T]) -> Callable[_P, _T | Awaitable[_ET_co]]: ...


class _WaitAfterDecorator(Protocol[_P, _T_contra, _AT_co]):
    """What `middleware(after=...)` returns for a sync `after`."""

    @overload
    def __call__(self, func: Callable[_P, _Coro[_T_contra]]) -> Callable[_P, _Coro[_AT_co]]: ...
    @overload
    def __call__(self, func: Callable[_P, _T_contra]) -> Callable[_P, _AT_co]: ...


class _AwaitAfterDecorator(Protocol[_P, _T, _AT_co]):
    """What `middleware(after=...)` returns for an async `after`."""

    @overload
    def __call__(self, func: Callable[_P, _Coro[_T]]) -> Callable[_P, _Coro[_AT_co]]: ...
    @overload
    def __call__(self, func: Callable[_P, _T]) -> Callable[_P, _T | Awaitable[_AT_co]]: ...


class _LazyCallAll(Protocol[_T_co]):
    """What `call_all(lazy=True)` returns: `call_all` again, with the captured functions prepended."""

    @overload
    def __call__(self, *funcs: Callable[[], _VT], lazy: _False = False) -> tuple[_T_co | _VT, ...]: ...
    @overload
    def __call__(self, *funcs: Callable[[], _VT], lazy: _True) -> _LazyCallAll[_T_co | _VT]: ...


__all__ = (
    "_AwaitAfterDecorator",
    "_AwaitOnErrorDecorator",
    "_LazyCallAll",
    "_WaitAfterDecorator",
    "_WaitOnErrorDecorator",
    "_Coro",
    "_ExcLogger",
    "_AT_co",
    "_ET_co",
)
