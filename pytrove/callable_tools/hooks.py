"""Wrapping a function with before, after and on-error hooks."""

from __future__ import annotations as _annotations

import functools
from typing import TYPE_CHECKING, Any, Concatenate, overload

from .._internal import _HARD_PROPAGATE
from ..async_tools import call_sync_or_await
from ._internal import _is_async_callable

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


# Direct form, async `func`: an async hook comes before a sync one, since a sync arm would
# take an async hook too and type its result as the coroutine it returns.
@overload
def middleware(
    func: Callable[_P, _Coro[_T]],
    *,
    before: MaybeAwaitableCallable[_P, Any] | None = None,
    on_error: None = None,
    after: None = None,
) -> Callable[_P, _Coro[_T]]: ...
@overload
def middleware(
    func: Callable[_P, _Coro[_T]],
    *,
    before: MaybeAwaitableCallable[_P, Any] | None = None,
    on_error: Callable[Concatenate[BaseException, _P], Awaitable[_ET_co]],
    after: None = None,
) -> Callable[_P, _Coro[_T | _ET_co]]: ...
@overload
def middleware(
    func: Callable[_P, _Coro[_T]],
    *,
    before: MaybeAwaitableCallable[_P, Any] | None = None,
    on_error: Callable[Concatenate[BaseException, _P], _ET_co],
    after: None = None,
) -> Callable[_P, _Coro[_T | _ET_co]]: ...
@overload
def middleware(
    func: Callable[_P, _Coro[_T]],
    *,
    before: MaybeAwaitableCallable[_P, Any] | None = None,
    on_error: None = None,
    after: Callable[Concatenate[_T, _P], Awaitable[_AT_co]],
) -> Callable[_P, _Coro[_AT_co]]: ...
@overload
def middleware(
    func: Callable[_P, _Coro[_T]],
    *,
    before: MaybeAwaitableCallable[_P, Any] | None = None,
    on_error: None = None,
    after: Callable[Concatenate[_T, _P], _AT_co],
) -> Callable[_P, _Coro[_AT_co]]: ...
@overload
def middleware(
    func: Callable[_P, _Coro[_T]],
    *,
    before: MaybeAwaitableCallable[_P, Any] | None = None,
    on_error: Callable[Concatenate[BaseException, _P], Awaitable[_ET_co]],
    after: Callable[Concatenate[_T | _ET_co, _P], Awaitable[_AT_co]],
) -> Callable[_P, _Coro[_AT_co]]: ...
@overload
def middleware(
    func: Callable[_P, _Coro[_T]],
    *,
    before: MaybeAwaitableCallable[_P, Any] | None = None,
    on_error: Callable[Concatenate[BaseException, _P], Awaitable[_ET_co]],
    after: Callable[Concatenate[_T | _ET_co, _P], _AT_co],
) -> Callable[_P, _Coro[_AT_co]]: ...
@overload
def middleware(
    func: Callable[_P, _Coro[_T]],
    *,
    before: MaybeAwaitableCallable[_P, Any] | None = None,
    on_error: Callable[Concatenate[BaseException, _P], _ET_co],
    after: Callable[Concatenate[_T | _ET_co, _P], Awaitable[_AT_co]],
) -> Callable[_P, _Coro[_AT_co]]: ...
@overload
def middleware(
    func: Callable[_P, _Coro[_T]],
    *,
    before: MaybeAwaitableCallable[_P, Any] | None = None,
    on_error: Callable[Concatenate[BaseException, _P], _ET_co],
    after: Callable[Concatenate[_T | _ET_co, _P], _AT_co],
) -> Callable[_P, _Coro[_AT_co]]: ...
# Direct form, sync `func`: hooks are sync (`middleware` raises `TypeError` for an async one).
@overload
def middleware(
    func: Callable[_P, _T],
    *,
    before: Callable[_P, Any] | None = None,
    on_error: None = None,
    after: None = None,
) -> Callable[_P, _T]: ...
@overload
def middleware(
    func: Callable[_P, _T],
    *,
    before: Callable[_P, Any] | None = None,
    on_error: Callable[Concatenate[BaseException, _P], _ET_co],
    after: None = None,
) -> Callable[_P, _T | _ET_co]: ...
@overload
def middleware(
    func: Callable[_P, _T],
    *,
    before: Callable[_P, Any] | None = None,
    on_error: None = None,
    after: Callable[Concatenate[_T, _P], _AT_co],
) -> Callable[_P, _AT_co]: ...
@overload
def middleware(
    func: Callable[_P, _T],
    *,
    before: Callable[_P, Any] | None = None,
    on_error: Callable[Concatenate[BaseException, _P], _ET_co],
    after: Callable[Concatenate[_T | _ET_co, _P], _AT_co],
) -> Callable[_P, _AT_co]: ...
# Decorator form: `func` is not known yet, so an async `after` or `on_error` returns a protocol
# that takes only an async function (`middleware` refuses async hooks on a sync one).
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
# With both, `on_error` returns what `after` takes, and `func` must return it too.
@overload
def middleware(
    func: None = None,
    *,
    before: Callable[_P, Any] | None = None,
    on_error: Callable[Concatenate[BaseException, _P], Awaitable[_T]],
    after: Callable[Concatenate[_T, _P], Awaitable[_AT_co]],
) -> _AwaitAfterDecorator[_P, _T, _AT_co]: ...
@overload
def middleware(
    func: None = None,
    *,
    before: Callable[_P, Any] | None = None,
    on_error: Callable[Concatenate[BaseException, _P], Awaitable[_T]],
    after: Callable[Concatenate[_T, _P], _AT_co],
) -> _AwaitAfterDecorator[_P, _T, _AT_co]: ...
@overload
def middleware(
    func: None = None,
    *,
    before: Callable[_P, Any] | None = None,
    on_error: Callable[Concatenate[BaseException, _P], _T],
    after: Callable[Concatenate[_T, _P], Awaitable[_AT_co]],
) -> _AwaitAfterDecorator[_P, _T, _AT_co]: ...
@overload
def middleware(
    func: None = None,
    *,
    before: Callable[_P, Any] | None = None,
    on_error: Callable[Concatenate[BaseException, _P], _T],
    after: Callable[Concatenate[_T, _P], _AT_co],
) -> _WaitAfterDecorator[_P, _T, _AT_co]: ...
def middleware(func: Callable[_P, Any] | None = None, **kw: Any) -> Any:
    """Wrap a sync or async function with hooks, directly or as a decorator.

    `before(*args, **kwargs)` runs first; an exception raised by `func` goes to
    `on_error(exc, *args, **kwargs)`, whose return value replaces the result
    (without it the exception propagates); `after(result, *args, **kwargs)`
    runs last, on `func`'s result or on `on_error`'s replacement, and its return
    value is the result. An exception raised by a hook itself propagates.
    `SystemExit` and `KeyboardInterrupt` never reach `on_error`; any other
    exception, `asyncio.CancelledError` and `GeneratorExit` included, does.

    `func` is async when it, or a layer it wraps (`__wrapped__`, a partial), is a
    coroutine function or an object with an async `__call__`; the wrapper is then a
    coroutine function, each hook may be sync or async, and a result is awaited
    only when it is awaitable. A sync `func` takes only sync hooks: a coroutine a
    sync `func` returns is a plain result to its hooks.

    Args:
        func: The function to wrap; omit it to get a decorator.
        **kw: `before`, `after` and `on_error`, each a callable or `None`.

    Returns:
        The wrapper, or a decorator when `func` is omitted.

    Raises:
        TypeError: For an unknown keyword or a hook that is not callable, from
            `middleware(...)` itself in both forms; for an async hook on a sync
            `func`, when `func` is given or the decorator is applied.

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
    for key, hook in kw.items():
        if key not in ("before", "after", "on_error"):
            msg = f"middleware() got an unexpected keyword argument {key!r}"
            raise TypeError(msg)

        if hook is not None and not callable(hook):
            msg = f"middleware() argument {key!r} must be callable or None"
            raise TypeError(msg)

    if func is None:
        return functools.partial(middleware, **kw)

    is_corofunc = _is_async_callable(func)

    for key, hook in kw.items():
        if hook is None:
            continue

        if is_corofunc:
            kw[key] = functools.partial(call_sync_or_await, hook)
        elif _is_async_callable(hook):
            msg = f"middleware() argument {key!r} is async, but {func!r} is sync -- it would never be awaited"
            raise TypeError(msg)

    before = kw.get("before")
    after = kw.get("after")
    on_error = kw.get("on_error")

    if is_corofunc:

        async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
            """Run `func` between its hooks, awaiting each."""
            if before is not None:
                await before(*args, **kwargs)

            try:
                result = await call_sync_or_await(func, *args, **kwargs)
            except _HARD_PROPAGATE:
                raise
            except BaseException as e:
                if on_error is None:
                    raise e
                result = await on_error(e, *args, **kwargs)

            if after is not None:
                result = await after(result, *args, **kwargs)

            return result
    else:

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
                    raise e
                result = on_error(e, *args, **kwargs)

            if after is not None:
                result = after(result, *args, **kwargs)

            return result

    return functools.wraps(func)(wrapper)


__all__ = ("middleware",)
