"""Helpers private to `callable_tools`: async detection and the protocols that spell decorator return types."""

from __future__ import annotations as _annotations

import inspect
from collections.abc import Callable, Coroutine
from typing import Any, Protocol, TypeAlias, TypeVar, overload

from .._internal import _iter_unwrap_layers
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
    """What `middleware(on_error=...)` returns for an async `on_error`, which only an async function takes."""

    def __call__(self, func: Callable[_P, _Coro[_T]]) -> Callable[_P, _Coro[_T | _ET_co]]: ...


class _WaitAfterDecorator(Protocol[_P, _T_contra, _AT_co]):
    """What `middleware(after=...)` returns when every hook is sync."""

    @overload
    def __call__(self, func: Callable[_P, _Coro[_T_contra]]) -> Callable[_P, _Coro[_AT_co]]: ...
    @overload
    def __call__(self, func: Callable[_P, _T_contra]) -> Callable[_P, _AT_co]: ...


class _AwaitAfterDecorator(Protocol[_P, _T_contra, _AT_co]):
    """What `middleware(after=...)` returns when `after` or `on_error` is async, which only an async function takes."""

    def __call__(self, func: Callable[_P, _Coro[_T_contra]]) -> Callable[_P, _Coro[_AT_co]]: ...


class _ConstantDecorator(Protocol[_T_co]):
    """What `return_constant(value=...)` returns: a coroutine function keeps returning a coroutine."""

    @overload
    def __call__(self, func: Callable[_P, _Coro[Any]]) -> Callable[_P, _Coro[_T_co]]: ...
    @overload
    def __call__(self, func: Callable[_P, Any]) -> Callable[_P, _T_co]: ...


class _LazyCallAll(Protocol[_T_co]):
    """What `call_all(lazy=True)` returns: `call_all` again, with the captured functions prepended."""

    @overload
    def __call__(
        self, *funcs: Callable[[], _VT], lazy: _False = False
    ) -> tuple[_T_co | _VT, ...]: ...
    @overload
    def __call__(self, *funcs: Callable[[], _VT], lazy: _True) -> _LazyCallAll[_T_co | _VT]: ...


def _is_async_callable(func: Callable[..., Any]) -> bool:
    """Tell whether calling `func` gives a coroutine.

    Sees through `__wrapped__` and partial layers, as `iscoroutinefunction_wrapped`
    does, and also counts an object whose class has an async `__call__`.

    Args:
        func: The callable to test.

    Returns:
        Whether `func`, or a layer under it, is a coroutine function or an async callable object.

    Raises:
        ValueError: If the layers loop back on themselves, as `_iter_unwrap_layers` reports.
    """
    return any(
        inspect.iscoroutinefunction(layer)
        or (callable(layer) and inspect.iscoroutinefunction(type(layer).__call__))
        for layer in _iter_unwrap_layers(func, unwrap_properties=False)
    )


__all__ = (
    "_AwaitAfterDecorator",
    "_AwaitOnErrorDecorator",
    "_ConstantDecorator",
    "_LazyCallAll",
    "_WaitAfterDecorator",
    "_WaitOnErrorDecorator",
    "_is_async_callable",
    "_Coro",
    "_ExcLogger",
    "_AT_co",
    "_ET_co",
)
