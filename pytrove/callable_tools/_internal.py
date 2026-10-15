"""Helpers private to `callable_tools`: the protocols that spell decorator return types."""

from __future__ import annotations as _annotations

from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, Protocol, TypeAlias, TypeVar, overload

from ..typings import _False, _P, _T, _True, _VT

_Coro: TypeAlias = Coroutine[Any, Any, _T]
"""A coroutine resolving to `_T`."""

_ET = TypeVar("_ET", covariant=True)
"""`middleware`'s `on_error` result type; covariant, since it only ever appears as a return."""

_AT = TypeVar("_AT", covariant=True)
"""`middleware`'s `after` result type; covariant for the same reason."""

_ExcLogger: TypeAlias = bool | Callable[[BaseException], Any]
"""`safe_call`'s `log_exc`: `True` to log, or a callback receiving the exception."""


class _WaitOnErrorDecorator(Protocol[_P, _ET]):
    """What `middleware(on_error=...)` returns for a sync `on_error`."""

    @overload
    def __call__(self, func: Callable[_P, _Coro[_T]]) -> Callable[_P, _Coro[_T | _ET]]: ...
    @overload
    def __call__(self, func: Callable[_P, _T]) -> Callable[_P, _T | _ET]: ...


class _AwaitOnErrorDecorator(Protocol[_P, _ET]):
    """What `middleware(on_error=...)` returns for an async `on_error`."""

    @overload
    def __call__(self, func: Callable[_P, _Coro[_T]]) -> Callable[_P, _Coro[_T | _ET]]: ...
    @overload
    def __call__(self, func: Callable[_P, _T]) -> Callable[_P, _T | Awaitable[_ET]]: ...


class _WaitAfterDecorator(Protocol[_P, _T, _AT]):
    """What `middleware(after=...)` returns for a sync `after`."""

    @overload
    def __call__(self, func: Callable[_P, _Coro[_T]]) -> Callable[_P, _Coro[_AT]]: ...
    @overload
    def __call__(self, func: Callable[_P, _T]) -> Callable[_P, _AT]: ...


class _AwaitAfterDecorator(Protocol[_P, _T, _AT]):
    """What `middleware(after=...)` returns for an async `after`."""

    @overload
    def __call__(self, func: Callable[_P, _Coro[_T]]) -> Callable[_P, _Coro[_AT]]: ...
    @overload
    def __call__(self, func: Callable[_P, _T]) -> Callable[_P, _T | Awaitable[_AT]]: ...


class _LazyCallAll(Protocol[_T]):
    """What `call_all(lazy=True)` returns: `call_all` again, with the captured functions prepended."""

    @overload
    def __call__(self, *funcs: Callable[[], _VT], lazy: _False = False) -> tuple[_T | _VT, ...]: ...
    @overload
    def __call__(self, *funcs: Callable[[], _VT], lazy: _True) -> _LazyCallAll[_T | _VT]: ...


__all__ = (
    "_AwaitAfterDecorator",
    "_AwaitOnErrorDecorator",
    "_LazyCallAll",
    "_WaitAfterDecorator",
    "_WaitOnErrorDecorator",
    "_Coro",
    "_ExcLogger",
    "_AT",
    "_ET",
)
