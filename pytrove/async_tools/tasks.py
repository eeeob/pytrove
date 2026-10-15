"""Waiting for and cancelling tasks without surprises."""

from __future__ import annotations as _annotations

import asyncio

from ..typings import _T
from .safety import asafe_call


async def safe_wait_task(task: asyncio.Task[_T], canceled_ok: bool = True, exc_ok: bool = False) -> _T | None:
    """Await a task, optionally tolerating its cancellation or failure.

    Args:
        task: The task to await.
        canceled_ok: Whether a cancellation returns `None` instead of raising.
        exc_ok: Whether a failure returns `None` instead of raising.

    Returns:
        The task's result, or `None` for a tolerated outcome.

    Raises:
        asyncio.CancelledError: If the task was cancelled and `canceled_ok` is false.
        Exception: Whatever the task raised, if `exc_ok` is false.
    """
    try:
        return await task
    except asyncio.CancelledError:
        if not canceled_ok:
            raise
    except Exception:
        if not exc_ok:
            raise

    return None


async def cancel_task(task: asyncio.Task, msg: str | None = None) -> bool:
    """Cancel a task and wait until the cancellation has been processed.

    Avoid cancelling a parent that is waiting on a child through another task:
    it can be interrupted before the child finishes handling the cancellation.

    Args:
        task: The task to cancel.
        msg: The cancellation message.

    Returns:
        `True` once the task accepted and processed the cancellation, `False`
        if it was already done.

    Raises:
        RuntimeError: If `task` is the current task.
    """
    if task is asyncio.current_task():
        msg_ = "Cannot cancel the current task"
        raise RuntimeError(msg_)

    if not task.cancel(msg):
        return False

    await asafe_call(task, include_exc=asyncio.CancelledError, log_exc=False, return_exc=False, raise_exc=False)
    return True


__all__ = (
    "safe_wait_task",
    "cancel_task",
)
