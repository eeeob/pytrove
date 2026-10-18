from __future__ import annotations as _annotations

import asyncio
from typing import Any

import pytest

from pytrove.async_tools._internal import _gather_cancel_on_error, _get_fut_loop, _wait_done


async def _value(v: Any, delay: float = 0) -> Any:
    """Return `v` after `delay` seconds."""
    await asyncio.sleep(delay)
    return v


async def _fail(exc: BaseException, delay: float = 0) -> None:
    """Raise `exc` after `delay` seconds."""
    await asyncio.sleep(delay)
    raise exc


async def _hang() -> None:
    """Wait until cancelled."""
    await asyncio.Event().wait()


class _ResultRaisingFuture(asyncio.Future):
    """A future that reports no exception, yet raises when its result is read."""

    def exception(self) -> BaseException | None:
        """Report no exception."""
        return None

    def result(self) -> Any:
        """Raise instead of returning.

        Raises:
            KeyError: Always.
        """
        msg = "odd"
        raise KeyError(msg)


async def test_gathering_future_cancel_skips_children_already_done() -> None:
    done = asyncio.get_running_loop().create_future()
    done.set_result(1)
    pending = asyncio.ensure_future(_value(2, delay=5))
    outer = _gather_cancel_on_error(done, pending)
    await asyncio.sleep(0)

    assert outer.cancel() is True
    assert not done.cancelled()

    with pytest.raises(asyncio.CancelledError):
        await outer

    assert pending.cancelled()


async def test_gathering_future_cancel_is_refused_once_every_child_is_done() -> None:
    child = asyncio.get_running_loop().create_future()
    outer = _gather_cancel_on_error(child)
    child.set_result(3)  # Its done callback is scheduled but has not run yet.

    assert outer.cancel() is False
    assert outer.cancel_message is None
    assert await outer == [3]


async def test_gather_cancel_on_error_retrieves_a_late_failure_after_it_failed() -> None:
    async def fails_while_unwinding() -> None:
        """Turn the cancellation into another error."""
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            msg = "late"
            raise ValueError(msg) from None

    late = asyncio.ensure_future(fails_while_unwinding())
    await asyncio.sleep(0)

    with pytest.raises(KeyError):
        await _gather_cancel_on_error(late, _fail(KeyError()))

    await asyncio.wait((late,))
    assert isinstance(late.exception(), ValueError)
    assert late._log_traceback is False  # Retrieved by the gather, so asyncio never warns about it.


async def test_gather_cancel_on_error_leaves_a_late_cancelled_child_alone() -> None:
    slow = asyncio.ensure_future(_value(1, delay=5))

    with pytest.raises(KeyError):
        await _gather_cancel_on_error(slow, _fail(KeyError()))

    await asyncio.wait((slow,))
    assert slow.cancelled()


async def test_gather_cancel_on_error_returns_a_cancelled_child_in_place() -> None:
    child = asyncio.ensure_future(_hang())
    asyncio.get_running_loop().call_soon(child.cancel)
    results = await _gather_cancel_on_error(child, _value(1), return_exceptions=True)

    assert isinstance(results[0], asyncio.CancelledError)
    assert results[1] == 1


async def test_gather_cancel_on_error_returns_an_error_raised_by_reading_a_result() -> None:
    odd = _ResultRaisingFuture()
    odd.set_result(None)
    results = await _gather_cancel_on_error(odd, return_exceptions=True)

    assert isinstance(results[0], KeyError)


async def test_gather_cancel_on_error_returning_exceptions_still_honours_a_cancel() -> None:
    outer = _gather_cancel_on_error(_value(1, delay=5), return_exceptions=True)
    await asyncio.sleep(0)
    assert outer.cancel("stop") is True

    with pytest.raises(asyncio.CancelledError) as caught:
        await outer

    assert caught.value.args == ("stop",)


async def test_gather_cancel_on_error_cancelled_without_a_message_has_an_empty_one() -> None:
    outer = _gather_cancel_on_error(_value(1, delay=5), return_exceptions=True)
    await asyncio.sleep(0)
    assert outer.cancel() is True
    assert outer.cancel_message == ""

    with pytest.raises(asyncio.CancelledError):
        await outer


def test_get_fut_loop_falls_back_to_the_private_loop_attribute() -> None:
    class _NoGetLoop:
        """A future-like object without `get_loop`."""

        _loop = object()

    fut: Any = _NoGetLoop()
    assert _get_fut_loop(fut) is _NoGetLoop._loop


async def test_wait_done_returns_at_once_for_a_done_task() -> None:
    task = asyncio.ensure_future(_fail(KeyError()))
    await asyncio.wait((task,))
    await _wait_done(task)  # Neither suspends nor raises the task's failure.
    assert isinstance(task.exception(), KeyError)


async def test_wait_done_waits_without_raising_the_tasks_outcome() -> None:
    failing = asyncio.ensure_future(_fail(KeyError(), delay=0.01))
    await _wait_done(failing)
    assert failing.done()
    assert isinstance(failing.exception(), KeyError)

    cancelled = asyncio.ensure_future(_hang())
    asyncio.get_running_loop().call_soon(cancelled.cancel)
    await _wait_done(cancelled)
    assert cancelled.cancelled()


async def test_wait_done_forwards_the_callers_cancellation_to_the_task() -> None:
    target = asyncio.ensure_future(_hang())
    caller = asyncio.ensure_future(_wait_done(target))
    await asyncio.sleep(0)
    caller.cancel()

    with pytest.raises(asyncio.CancelledError):
        await caller

    await asyncio.wait((target,))
    assert target.cancelled()
