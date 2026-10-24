"""Wrapping a function with before, after and on-error hooks."""

from __future__ import annotations as _annotations

import functools
from typing import TYPE_CHECKING, Any, Concatenate, overload

from .._internal import _HARD_PROPAGATE
from ..async_tools import call_sync_or_await
from ..validate_tools import iscoroutinefunction_wrapped

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ..typings import MaybeAwaitableCallable, _P, _T
    from ._internal import (
        _AwaitAfterDecorator,
        _AwaitOnErrorDecorator,
        _Coro,
        _WaitAfterDecorator,
        _WaitOnErrorDecorator,
        _AT_co,
        _ET_co,
    )


@overload
def middleware(
    func: Callable[_P, _Coro[_T]],
    *,
    before: MaybeAwaitableCallable[_P, Any] | None = None,
    after: None = None,
    on_error: None = None,
) -> Callable[_P, _Coro[_T]]: ...
@overload
def middleware(
    func: Callable[_P, _Coro[_T]],
    *,
    before: MaybeAwaitableCallable[_P, Any] | None = None,
    after: None = None,
    on_error: MaybeAwaitableCallable[Concatenate[BaseException, _P], _ET_co],
) -> Callable[_P, _Coro[_T | _ET_co]]: ...
@overload
def middleware(
    func: Callable[_P, _Coro[_T]],
    *,
    before: MaybeAwaitableCallable[_P, Any] | None = None,
    after: MaybeAwaitableCallable[Concatenate[_T, _P], _AT_co],
    on_error: None = None,
) -> Callable[_P, _Coro[_AT_co]]: ...
@overload
def middleware(
    func: Callable[_P, _Coro[_T]],
    *,
    before: MaybeAwaitableCallable[_P, Any] | None = None,
    on_error: MaybeAwaitableCallable[Concatenate[BaseException, _P], _ET_co],
    after: MaybeAwaitableCallable[Concatenate[_T | _ET_co, _P], _AT_co],
) -> Callable[_P, _Coro[_AT_co]]: ...
@overload
def middleware(
    func: Callable[_P, _T],
    *,
    before: Callable[_P, Any] | None = None,
    after: None = None,
    on_error: None = None,
) -> Callable[_P, _T]: ...
@overload
def middleware(
    func: Callable[_P, _T],
    *,
    before: Callable[_P, Any] | None = None,
    after: None = None,
    on_error: Callable[Concatenate[BaseException, _P], _ET_co],
) -> Callable[_P, _T | _ET_co]: ...
@overload
def middleware(
    func: Callable[_P, _T],
    *,
    before: Callable[_P, Any] | None = None,
    after: Callable[Concatenate[_T, _P], _AT_co],
    on_error: None = None,
) -> Callable[_P, _AT_co]: ...
@overload
def middleware(
    func: Callable[_P, _T],
    *,
    before: Callable[_P, Any] | None = None,
    on_error: Callable[Concatenate[BaseException, _P], _ET_co],
    after: Callable[Concatenate[_T | _ET_co, _P], _AT_co],
) -> Callable[_P, _AT_co]: ...
@overload
def middleware(
    func: None = None,
    *,
    before: Callable[_P, Any] | None = None,
    after: None = None,
    on_error: None = None,
) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]: ...
@overload
def middleware(
    func: None = None,
    *,
    before: Callable[_P, Any] | None = None,
    after: None = None,
    on_error: Callable[Concatenate[BaseException, _P], Awaitable[_ET_co]],
) -> _AwaitOnErrorDecorator[_P, _ET_co]: ...
@overload
def middleware(
    func: None = None,
    *,
    before: Callable[_P, Any] | None = None,
    after: None = None,
    on_error: Callable[Concatenate[BaseException, _P], _ET_co],
) -> _WaitOnErrorDecorator[_P, _ET_co]: ...
@overload
def middleware(
    func: None = None,
    *,
    before: Callable[_P, Any] | None = None,
    after: Callable[Concatenate[_T, _P], Awaitable[_AT_co]],
    on_error: None = None,
) -> _AwaitAfterDecorator[_P, _T, _AT_co]: ...
@overload
def middleware(
    func: None = None,
    *,
    before: Callable[_P, Any] | None = None,
    after: Callable[Concatenate[_T, _P], _AT_co],
    on_error: None = None,
) -> _WaitAfterDecorator[_P, _T, _AT_co]: ...
def middleware(func: Callable[_P, Any] | None = None, **kw: Any) -> Any:
    """Wrap a sync or async function with hooks, directly or as a decorator.

    `before(*args, **kwargs)` runs first; an exception raised by `func` goes to
    `on_error(exc, *args, **kwargs)`, whose return value replaces the result
    (without it the exception propagates); `after(result, *args, **kwargs)`
    runs last and its return value is the result. An exception raised by a hook
    itself propagates. For an async function each hook may be sync or async.
    `SystemExit` and `KeyboardInterrupt` never reach `on_error`.

    Args:
        func: The function to wrap; omit it to get a decorator.
        **kw: `before`, `after` and `on_error`, each a callable or `None`.

    Returns:
        The wrapper, or a decorator when `func` is omitted.

    Raises:
        TypeError: For an unknown keyword or a hook that is not callable.

    Example:
        >>> def add(a, b):
        ...     return a + b
        >>> wrapped = middleware(add, before=lambda a, b: print("adding", a, b), after=lambda result, a, b: result * 10)
        >>> wrapped(1, 2)
        adding 1 2
        30
        >>> @middleware(on_error=lambda exc, a, b: float("inf"))
        ... def div(a, b):
        ...     return a / b
        >>> div(1, 0)
        inf
    """
    if func is None:
        return functools.partial(middleware, **kw)

    is_corofunc = iscoroutinefunction_wrapped(func)

    for key in list(kw):
        if key not in ("before", "after", "on_error"):
            msg = f"middleware() got an unexpected keyword argument {key!r}"
            raise TypeError(msg)

        if (hook := kw[key]) is None:
            continue

        if not callable(hook):
            msg = f"middleware() argument {key!r} must be callable or None"
            raise TypeError(msg)

        kw[key] = functools.partial(call_sync_or_await, hook) if is_corofunc else hook

    before = kw.get("before")
    after = kw.get("after")
    on_error = kw.get("on_error")

    if is_corofunc:

        async def async_wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
            """Run `func` between its hooks, awaiting each."""
            if before is not None:
                await before(*args, **kwargs)

            try:
                result = await func(*args, **kwargs)
            except _HARD_PROPAGATE:
                raise
            except BaseException as e:
                if on_error is None:
                    raise
                result = await on_error(e, *args, **kwargs)

            if after is not None:
                result = await after(result, *args, **kwargs)

            return result

        return functools.wraps(func)(async_wrapper)

    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
        """Run `func` between its hooks."""
        if before is not None:
            before(*args, **kwargs)

        try:
            result = func(*args, **kwargs)
        except _HARD_PROPAGATE:
            raise
        except BaseException as e:
            if on_error is None:
                raise
            result = on_error(e, *args, **kwargs)

        if after is not None:
            result = after(result, *args, **kwargs)

        return result

    return functools.wraps(func)(wrapper)


__all__ = ("middleware",)
