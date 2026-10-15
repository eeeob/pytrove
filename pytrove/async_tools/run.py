"""Running sync code from async code, and small awaitable adapters."""

from __future__ import annotations as _annotations

import asyncio
import contextvars
import functools
import inspect
import traceback
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, overload

from ..typings import MaybeAwaitableCallable, _P, _T, _True
from ._internal import _log_exc


@overload
async def to_thread(
    func: Callable[_P, _T],
    *args: _P.args,
    executor: ThreadPoolExecutor | None = None,
    log_exc: bool = True,
    **kwargs: _P.kwargs,
) -> _T: ...
@overload
async def to_thread(
    func: Callable[_P, _T],
    *args: _P.args,
    executor: ThreadPoolExecutor | None = None,
    log_exc: bool = True,
    return_exc: _True,
    **kwargs: _P.kwargs,
) -> _T | Exception: ...
async def to_thread(
    func: Callable[..., Any],
    *args: Any,
    executor: ThreadPoolExecutor | None = None,
    log_exc: bool = True,
    return_exc: bool = False,
    **kwargs: Any,
) -> Any:
    """Run a sync function in an executor thread, with the caller's context variables.

    Args:
        func: The function to run.
        *args: Its positional arguments.
        executor: The executor; the loop's default one when `None`.
        log_exc: Whether to log a failure with the caller's stack.
        return_exc: Whether to return a failure instead of raising it.
        **kwargs: Its keyword arguments.

    Returns:
        The function's result, or the exception when `return_exc` is set.

    Raises:
        Exception: Whatever the function raised, unless `return_exc` is set.
    """
    caller_stack = traceback.extract_stack()[:-1] if log_exc else None
    loop = asyncio.get_running_loop()
    call = functools.partial(contextvars.copy_context().run, func, *args, **kwargs)

    try:
        return await loop.run_in_executor(executor, call)
    except Exception as e:
        if log_exc:
            _log_exc("error in to_thread", caller_stack, e)

        if return_exc:
            return e

        raise


async def call_sync_or_await(func: MaybeAwaitableCallable[_P, _T], *args: _P.args, **kwargs: _P.kwargs) -> _T:
    """Call a function and await its result if it is awaitable.

    Args:
        func: A sync or async callable.
        *args: Its positional arguments.
        **kwargs: Its keyword arguments.

    Returns:
        The result, awaited when needed.
    """
    result = func(*args, **kwargs)

    if inspect.isawaitable(result):
        result = await result

    return result


async def run_awaitable_in_coro(awaitable: Awaitable[_T]) -> _T:
    """Await any awaitable inside a real coroutine, for APIs that only take coroutines.

    Args:
        awaitable: The awaitable.

    Returns:
        Its result.
    """
    return await awaitable


async def yield_control() -> None:
    """Let other tasks run for one loop iteration, inside a long stretch without awaits."""
    await asyncio.sleep(0)


__all__ = (
    "to_thread",
    "call_sync_or_await",
    "run_awaitable_in_coro",
    "yield_control",
)
