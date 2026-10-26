from __future__ import annotations as _annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from pytrove.async_tools import cancel_task, safe_wait_task

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


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


async def _value(v: Any, delay: float = 0) -> Any:
    """Return `v` after `delay` seconds."""
    await asyncio.sleep(delay)
    return v


async def _fail(exc: BaseException, delay: float = 0) -> None:
    """Raise `exc` after `delay` seconds."""
    await asyncio.sleep(delay)
    raise exc


async def test_safe_wait_task_tolerates_what_it_is_told_to() -> None:
    assert await safe_wait_task(asyncio.ensure_future(_value(3))) == 3

    cancelled = asyncio.ensure_future(_value(1, delay=5))
    cancelled.cancel()
    assert await safe_wait_task(cancelled) is None

    cancelled = asyncio.ensure_future(_value(1, delay=5))
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await safe_wait_task(cancelled, canceled_ok=False)

    assert await safe_wait_task(asyncio.ensure_future(_fail(KeyError())), exc_ok=True) is None

    with pytest.raises(KeyError):
        await safe_wait_task(asyncio.ensure_future(_fail(KeyError())))


async def test_cancel_task_waits_for_the_cancellation() -> None:
    task = asyncio.ensure_future(_value(1, delay=5))
    await asyncio.sleep(0)
    assert await cancel_task(task) is True
    assert task.cancelled()
    assert await cancel_task(task) is False


async def test_cancel_task_refuses_the_current_task() -> None:
    current = asyncio.current_task()
    assert current is not None

    with pytest.raises(RuntimeError, match="current task"):
        await cancel_task(current)


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


async def test_cancel_task_passes_its_message_to_the_task() -> None:
    seen: list[tuple[Any, ...]] = []

    async def record() -> None:
        """Record the cancellation's arguments, then let it through."""
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError as e:
            seen.append(e.args)
            raise

    task = asyncio.ensure_future(record())
    await asyncio.sleep(0)

    assert await cancel_task(task, "why") is True
    assert seen == [("why",)]


async def test_cancel_task_raises_what_the_task_raised_instead() -> None:
    async def convert() -> None:
        """Turn the cancellation into another error."""
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            msg = "converted"
            raise ValueError(msg) from None

    task = asyncio.ensure_future(convert())
    await asyncio.sleep(0)

    with pytest.raises(ValueError, match="converted"):
        await cancel_task(task)


async def test_cancel_task_reports_a_swallowed_cancellation() -> None:
    async def swallow() -> int:
        """Catch the cancellation and return normally."""
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            return 1

        return 0

    task = asyncio.ensure_future(swallow())
    await asyncio.sleep(0)

    assert await cancel_task(task) is False
    assert not task.cancelled()
    assert task.result() == 1


async def test_safe_wait_task_never_tolerates_a_base_exception() -> None:
    class _Abort(BaseException):
        """A failure that is not an `Exception`."""

    task = asyncio.ensure_future(_fail(_Abort()))

    with pytest.raises(_Abort):
        await safe_wait_task(task, exc_ok=True)
