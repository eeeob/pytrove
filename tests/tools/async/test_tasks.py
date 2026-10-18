from __future__ import annotations as _annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from pytrove.async_tools import cancel_task, safe_wait_task


async def _slow_to_unwind() -> None:
    """Sleep until cancelled, then take a while to finish unwinding."""
    try:
        await asyncio.sleep(10)
    except asyncio.CancelledError:
        await asyncio.sleep(0.05)
        raise


async def _hang() -> None:
    """Sleep long enough to be cancelled first."""
    await asyncio.sleep(10)


@pytest.mark.parametrize(
    "wait",
    [
        pytest.param(cancel_task, id="cancel_task"),
        pytest.param(safe_wait_task, id="safe_wait_task"),
    ],
)
async def test_waiting_on_a_task_keeps_the_callers_own_cancellation(
    wait: Callable[[asyncio.Task[Any]], Awaitable[Any]],
) -> None:
    target = asyncio.ensure_future(_slow_to_unwind() if wait is cancel_task else _hang())
    await asyncio.sleep(0)
    reached: list[bool] = []

    async def waiter() -> None:
        """Wait on `target`, then record that it carried on."""
        await wait(target)
        reached.append(True)

    caller = asyncio.ensure_future(waiter())
    await asyncio.sleep(0.01)
    caller.cancel()

    with pytest.raises(asyncio.CancelledError):
        await caller

    assert caller.cancelled()
    assert not reached
    await asyncio.gather(target, return_exceptions=True)
    assert target.cancelled()  # The caller's cancellation still reaches the task it waited on.
