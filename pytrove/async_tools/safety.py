"""Awaiting and calling with exception handling built in."""

from __future__ import annotations as _annotations

import inspect
import logging
import traceback
from collections.abc import Awaitable, Callable, Iterator
from typing import TYPE_CHECKING, Any, cast, overload

from .._internal._exceptions import _HARD_PROPAGATE
from ..iter_tools import iter_flat_cont
from ..validate_tools import is_container, is_exception, iscoroutinefunction_wrapped
from ._internal import _log_exc, _ExcLogger
from .run import call_sync_or_await, to_thread

if TYPE_CHECKING:
    from concurrent.futures import ThreadPoolExecutor

    from .._internal._types import _ExcFilter
    from ..typings import Container, MaybeAwaitable, NestedContainer, _ExcT, _False, _T, _True

log = logging.getLogger(__name__)


# Each shape lists `return_exc=False` first, so a plain `bool` (or `True`, or nothing) falls to the
# arm that may return an exception.
@overload
async def safe_await(
    awaitables: Awaitable[_T], *, return_exc: _False, log_exc: bool = True
) -> _T: ...
@overload
async def safe_await(
    awaitables: Awaitable[_T], *, return_exc: bool = True, log_exc: bool = True
) -> _T | Exception: ...
@overload
async def safe_await(
    awaitables: Container[NestedContainer[Awaitable[_T] | None]],
    *,
    return_exc: _False,
    log_exc: bool = True,
) -> list[_T]: ...
@overload
async def safe_await(
    awaitables: Container[NestedContainer[Awaitable[_T] | None]],
    *,
    return_exc: bool = True,
    log_exc: bool = True,
) -> list[_T | Exception]: ...
@overload
async def safe_await(
    *awaitables: NestedContainer[Awaitable[_T] | None],
    return_exc: _False,
    log_exc: bool = True,
) -> list[_T]: ...
@overload
async def safe_await(
    *awaitables: NestedContainer[Awaitable[_T] | None],
    return_exc: bool = True,
    log_exc: bool = True,
) -> list[_T | Exception]: ...
async def safe_await(*awaitables: Any, return_exc: bool = True, log_exc: bool = True) -> Any:
    """Await awaitables one after another, returning failures instead of raising.

    A single bare awaitable gives its result unwrapped; a container, or
    several arguments, give a list.

    Args:
        *awaitables: Awaitables, or containers of them, at any depth.
        return_exc: Whether failures are returned in place; otherwise the first one is raised.
        log_exc: Whether to log each failure with the caller's stack.

    Returns:
        The result, or the list of results, in order.

    Raises:
        Exception: The first failure, when `return_exc` is false.

    Example:
        >>> import asyncio
        >>> async def fail():
        ...     raise ValueError("boom")
        >>> asyncio.run(safe_await(asyncio.sleep(0, result=1)))
        1
        >>> asyncio.run(safe_await(asyncio.sleep(0, result=1), fail(), log_exc=False))
        [1, ValueError('boom')]
    """
    is_not_cont_first = not is_container(awaitables[0]) if awaitables else True
    caller_stack = traceback.extract_stack()[:-1] if log_exc else None
    results = []
    is_multi = False

    # `ty` binds `_T` to the container arm of the recursive `NestedContainer[_T]`, so
    # it cannot recover the leaf type (astral-sh/ty#1703); the parameter states it.
    leaves = cast(Iterator[Awaitable[Any]], iter_flat_cont(awaitables))

    for i, awaitable in enumerate(leaves):
        is_multi = is_multi or i > 0

        try:
            result = await awaitable
        except Exception as e:
            result = e

        if is_exception(result):
            if log_exc:
                _log_exc("error in safe_await", caller_stack, result, index=i if is_multi else None)

            if not return_exc:
                raise result

        results.append(result)

    return results[0] if len(results) == 1 and is_not_cont_first else results


@overload
async def asafe_call(
    awaitable: Awaitable[_T],
    *,
    include_exc: _ExcFilter = None,
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
) -> _T | None: ...
@overload
async def asafe_call(
    awaitable: Awaitable[_T],
    *,
    return_exc: _False,
    include_exc: _ExcFilter = None,
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
) -> _T | None: ...
@overload
async def asafe_call(
    awaitable: Awaitable[_T],
    *,
    return_exc: _True,
    include_exc: type[_ExcT],
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
) -> _T | _ExcT: ...
@overload
async def asafe_call(
    awaitable: Awaitable[_T],
    *,
    return_exc: _True,
    include_exc: tuple[type[_ExcT], ...],
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
) -> _T | _ExcT: ...
@overload
async def asafe_call(
    awaitable: Awaitable[_T],
    *,
    return_exc: _True,
    include_exc: _ExcFilter = None,
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
) -> _T | BaseException: ...
@overload
async def asafe_call(
    awaitable: Awaitable[_T],
    *,
    raise_exc: _True,
    include_exc: _ExcFilter = None,
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
) -> _T: ...
async def asafe_call(
    awaitable: Awaitable[Any],
    *,
    return_exc: bool = False,
    raise_exc: bool = False,
    include_exc: _ExcFilter = None,
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
) -> Any:
    """Await one awaitable, swallowing what it raises: the async `safe_call`.

    `exclude_exc` always propagates and wins over `include_exc`; without
    `include_exc` everything else is swallowed. `SystemExit` and
    `KeyboardInterrupt` always propagate. An error raised by `log_exc` itself
    propagates, with the original attached as its context.

    Args:
        awaitable: The awaitable.
        return_exc: Whether to return a swallowed exception instead of `None`.
        raise_exc: Whether to re-raise after `log_exc` ran, for the logging alone.
        include_exc: The exceptions to swallow; `None` for all.
        exclude_exc: The exceptions that always propagate.
        log_exc: `True` to log a swallowed exception, or a sync or async callback receiving it.

    Returns:
        The result, or `None` / the exception after a swallowed failure.

    Raises:
        TypeError: If `return_exc` and `raise_exc` are both set, or `exclude_exc`
            names an exception that always propagates anyway.
        BaseException: Whatever is not swallowed, or anything when `raise_exc` is set.

    Example:
        >>> import asyncio
        >>> async def fail():
        ...     raise ValueError("boom")
        >>> asyncio.run(asafe_call(fail())) is None
        True
        >>> asyncio.run(asafe_call(fail(), return_exc=True))
        ValueError('boom')
        >>> asyncio.run(asafe_call(fail(), include_exc=KeyError))
        Traceback (most recent call last):
        ValueError: boom
    """
    if return_exc and raise_exc:
        msg = "asafe_call: return_exc and raise_exc cannot both be True -- raise_exc means the exception is never returned, only re-raised"
        raise TypeError(msg)

    if exclude_exc is not None:
        for exc_type in exclude_exc if isinstance(exclude_exc, tuple) else (exclude_exc,):
            if issubclass(exc_type, _HARD_PROPAGATE):
                msg = f"exclude_exc: {exc_type.__name__} always propagates already -- no need to list it"
                raise TypeError(msg)

    try:
        return await awaitable
    except _HARD_PROPAGATE:
        raise
    except BaseException as e:
        if exclude_exc is not None and isinstance(e, exclude_exc):
            raise

        if include_exc is not None and not isinstance(e, include_exc):
            raise

        if log_exc:
            if callable(log_exc):
                await call_sync_or_await(log_exc, e)
            else:
                log.error("error in asafe_call(%r)", awaitable, exc_info=e)

        if raise_exc:
            raise

        if return_exc:
            return e

    return None


# Same overload order as `safe_await`: `return_exc=False` (or nothing) first, so `True` or a
# plain `bool` falls to the arm that may return an exception. The coroutine-function and the
# sync-callable shapes come before `MaybeAwaitable`, whose `Coroutine[..., R] | R` return would
# otherwise bind `R` to the whole coroutine; `MaybeAwaitable` stays last for union-typed values.
@overload
async def maybe_awaitable(
    awaitable_or_callable: Callable[..., Awaitable[_T]],
    *args: Any,
    executor: ThreadPoolExecutor | None = None,
    return_exc: _False = False,
    log_exc: bool = True,
    **kwargs: Any,
) -> _T: ...
@overload
async def maybe_awaitable(
    awaitable_or_callable: Callable[..., Awaitable[_T]],
    *args: Any,
    executor: ThreadPoolExecutor | None = None,
    return_exc: bool,
    log_exc: bool = True,
    **kwargs: Any,
) -> _T | Exception: ...
@overload
async def maybe_awaitable(
    awaitable_or_callable: Callable[..., _T],
    *args: Any,
    executor: ThreadPoolExecutor | None = None,
    return_exc: _False = False,
    log_exc: bool = True,
    **kwargs: Any,
) -> _T: ...
@overload
async def maybe_awaitable(
    awaitable_or_callable: Callable[..., _T],
    *args: Any,
    executor: ThreadPoolExecutor | None = None,
    return_exc: bool,
    log_exc: bool = True,
    **kwargs: Any,
) -> _T | Exception: ...
@overload
async def maybe_awaitable(
    awaitable_or_callable: MaybeAwaitable[..., _T],
    *args: Any,
    executor: ThreadPoolExecutor | None = None,
    return_exc: _False = False,
    log_exc: bool = True,
    **kwargs: Any,
) -> _T: ...
@overload
async def maybe_awaitable(
    awaitable_or_callable: MaybeAwaitable[..., _T],
    *args: Any,
    executor: ThreadPoolExecutor | None = None,
    return_exc: bool,
    log_exc: bool = True,
    **kwargs: Any,
) -> _T | Exception: ...
async def maybe_awaitable(
    awaitable_or_callable: Any,
    *args: Any,
    executor: ThreadPoolExecutor | None = None,
    return_exc: bool = False,
    log_exc: bool = True,
    **kwargs: Any,
) -> Any:
    """Await an awaitable, call a coroutine function, or run a sync function in a thread.

    Args:
        awaitable_or_callable: An awaitable, a coroutine function, or a sync callable.
        *args: Positional arguments for a callable.
        executor: The executor for a sync callable.
        return_exc: Whether to return a failure instead of raising it.
        log_exc: Whether to log a failure with the caller's stack.
        **kwargs: Keyword arguments for a callable.

    Returns:
        The result, or the exception when `return_exc` is set.

    Raises:
        TypeError: If arguments are given with an awaitable, or the value is neither awaitable nor callable.

    Example:
        >>> import asyncio
        >>> async def double(x):
        ...     return x * 2
        >>> asyncio.run(maybe_awaitable(double(2)))
        4
        >>> asyncio.run(maybe_awaitable(double, 3))
        6
        >>> asyncio.run(maybe_awaitable(len, "abcd"))
        4
    """
    if inspect.isawaitable(awaitable_or_callable):
        if args or kwargs:
            msg = "Cannot pass args/kwargs to an already-created awaitable"
            raise TypeError(msg)

        return await safe_await(awaitable_or_callable, return_exc=return_exc, log_exc=log_exc)

    if iscoroutinefunction_wrapped(awaitable_or_callable):
        return await safe_await(
            awaitable_or_callable(*args, **kwargs), return_exc=return_exc, log_exc=log_exc
        )

    if callable(awaitable_or_callable):
        return await to_thread(
            awaitable_or_callable,
            *args,
            executor=executor,
            return_exc=return_exc,
            log_exc=log_exc,
            **kwargs,
        )

    msg = f"Expected an Awaitable or Callable, got {type(awaitable_or_callable).__name__!r}"
    raise TypeError(msg)


__all__ = (
    "safe_await",
    "asafe_call",
    "maybe_awaitable",
)
