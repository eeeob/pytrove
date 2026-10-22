"""Helpers private to `async_tools`: background-thread loops and tracked submissions."""

from __future__ import annotations as _annotations

import asyncio
import inspect
import sys
import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

    from ..typings import _T

def _check_loop_factory(loop_factory: Callable[[], asyncio.AbstractEventLoop] | None) -> None:
    """Validate a `loop_factory`, warning that Python before 3.12 ignores it.

    Args:
        loop_factory: The factory, or `None`.

    Raises:
        TypeError: If it is not callable.
    """
    if loop_factory is not None and not callable(loop_factory):
        msg = f"loop_factory must be callable, got {type(loop_factory).__name__!r}"
        raise TypeError(msg)

    if sys.version_info < (3, 12) and loop_factory is not None:
        warnings.warn(
            "loop_factory is ignored on Python < 3.12 (asyncio.run() has no loop_factory parameter there); "
            "falling back to a plain asyncio.run()",
            stacklevel=3,
        )


def _run_loop(coro: Coroutine[Any, Any, Any], loop_factory: Callable[[], asyncio.AbstractEventLoop] | None) -> None:
    """Drive a coroutine with `asyncio.run`, passing `loop_factory` where Python accepts it.

    Args:
        coro: The coroutine.
        loop_factory: The loop factory; ignored before 3.12.
    """
    if sys.version_info < (3, 12):
        asyncio.run(coro)
    else:
        asyncio.run(coro, loop_factory=loop_factory)


async def _run_tracked(
    func: Callable[..., Awaitable[_T]],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    tasks: set[asyncio.Task[Any]] | None,
    slots: asyncio.Semaphore | None,
) -> _T:
    """Run one submission on the worker's loop, tracked for the drain and bounded by the semaphore.

    `func` is called here, on the worker's loop, so it may touch that loop. The
    task registers before waiting for a slot, so a drain sees it even while parked.

    Args:
        func: The awaitable function.
        args: Its positional arguments.
        kwargs: Its keyword arguments.
        tasks: The worker's live task set.
        slots: The concurrency cap, or `None` for none.

    Returns:
        The result.

    Raises:
        TypeError: If calling `func` does not give an awaitable.
    """
    awaitable = func(*args, **kwargs)

    if not inspect.isawaitable(awaitable):
        msg = f"func must be an awaitable function; calling it returned {type(awaitable).__name__!r}"
        raise TypeError(msg)

    task = asyncio.current_task()

    # Always a task in practice (`submit` awaits it in a task or schedules it as one); the
    # check only narrows `current_task`'s `Task | None` for the set.
    if tasks is not None and task is not None:
        tasks.add(task)

    try:
        if slots is None:
            return await awaitable

        await slots.acquire()

        try:
            return await awaitable
        finally:
            slots.release()  # Synchronous, so a cancellation cannot leak the slot.
    finally:
        if tasks is not None and task is not None:
            tasks.discard(task)


__all__ = (
    "_check_loop_factory",
    "_run_loop",
    "_run_tracked",
)
