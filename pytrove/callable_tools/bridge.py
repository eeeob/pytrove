"""Crossing between sync and async calling conventions."""

from __future__ import annotations as _annotations

import asyncio
import functools
from typing import TYPE_CHECKING, Any

from .._internal._asyncio import _get_running_loop
from ..async_tools import run_awaitable_in_coro

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ..typings import _P, _T
    from ._internal import _Coro


async def await_sync(func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
    """Call a sync function from a coroutine, on the loop's own thread.

    Args:
        func: The function.
        *args: Its positional arguments.
        **kwargs: Its keyword arguments.

    Returns:
        Its result.
    """
    return func(*args, **kwargs)


def to_coroutine(func: Callable[_P, _T]) -> Callable[_P, _Coro[_T]]:
    """Turn a sync function into a coroutine function that calls it.

    Args:
        func: The function.

    Returns:
        A coroutine function with `func`'s name and signature.
    """

    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Call `func`."""
        return func(*args, **kwargs)

    return functools.wraps(func)(wrapper)


def run_awaitable_sync(
    awaitable: Awaitable[_T], loop: asyncio.AbstractEventLoop | None = None
) -> _T:
    """Run an awaitable to completion from synchronous code.

    Without `loop`, a fresh loop runs it through `asyncio.run`; use
    `SyncAwaitableRunner` to reuse one loop across calls. With `loop`, that loop
    must already be running in another thread, and this blocks until done.

    Args:
        awaitable: The awaitable.
        loop: A loop running in another thread, or `None` for a fresh one.

    Returns:
        The awaitable's result.

    Raises:
        RuntimeError: If `loop` is closed or idle, if a loop runs in this thread
            and no `loop` was given, or if `loop` is this thread's own loop.

    Example:
        >>> run_awaitable_sync(asyncio.sleep(0, result=1))
        1
    """
    if loop is not None:
        if loop.is_closed():
            msg = "cannot use a closed event loop"
            raise RuntimeError(msg)

        if not loop.is_running():
            msg = (
                "the given event loop is not running -- driving an idle loop directly here risks a conflict "
                "with another thread starting it at the same time; start the loop in its own thread first, "
                "or pass loop=None to let this call create and own a fresh loop"
            )
            raise RuntimeError(msg)

    if (running_loop := _get_running_loop()) is not None:
        if loop is None:
            msg = (
                "an event loop is already running in the calling thread, so a new loop cannot be created "
                "and driven here -- pass an explicit `loop` that is running in another thread"
            )
            raise RuntimeError(msg)

        if loop is running_loop:
            msg = (
                "cannot target the event loop already running in the calling thread -- blocking here to "
                "wait for it would deadlock that same loop"
            )
            raise RuntimeError(msg)

    coro = awaitable if asyncio.iscoroutine(awaitable) else run_awaitable_in_coro(awaitable)

    if loop is None:
        return asyncio.run(coro)

    return asyncio.run_coroutine_threadsafe(coro, loop).result()


__all__ = (
    "await_sync",
    "to_coroutine",
    "run_awaitable_sync",
)
