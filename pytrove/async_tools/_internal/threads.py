"""Helpers private to `async_tools`: closing refused coroutines and driving background-thread loops."""

from __future__ import annotations as _annotations

import asyncio
import inspect
import sys
import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


def _close_if_unstarted(awaitable: object) -> None:
    """Close a coroutine that never started, so a refused one does not warn it was never awaited.

    Args:
        awaitable: Any awaitable; anything but a coroutine not yet started is left alone.
    """
    if (
        inspect.iscoroutine(awaitable)
        and inspect.getcoroutinestate(awaitable) == inspect.CORO_CREATED
    ):
        awaitable.close()


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


def _run_loop(
    coro: Coroutine[Any, Any, Any], loop_factory: Callable[[], asyncio.AbstractEventLoop] | None
) -> None:
    """Drive a coroutine with `asyncio.run`, passing `loop_factory` where Python accepts it.

    Args:
        coro: The coroutine.
        loop_factory: The loop factory; ignored before 3.12.
    """
    try:
        if sys.version_info < (3, 12):
            asyncio.run(coro)
        else:
            asyncio.run(coro, loop_factory=loop_factory)
    except BaseException:
        # `asyncio.run` can fail before it takes `coro` (a raising `loop_factory`): close it,
        # so it does not warn that it was never awaited.
        _close_if_unstarted(coro)
        raise


__all__ = (
    "_close_if_unstarted",
    "_check_loop_factory",
    "_run_loop",
)
