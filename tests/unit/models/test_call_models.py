from __future__ import annotations as _annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from pytrove.enums import TriggerOn
from pytrove.models import DeferredCall, DelayedCallback


def test_deferred_call_runs_only_on_matching_results() -> None:
    error = ValueError("x")

    assert DeferredCall(print).should_run(1)
    assert not DeferredCall(print).should_run(error)
    assert DeferredCall(print, when=TriggerOn.ERROR).should_run(error)
    assert not DeferredCall(print, when=TriggerOn.ERROR).should_run(1)
    assert DeferredCall(print, when=TriggerOn.ALWAYS).should_run(error)


async def test_deferred_call_appends_arguments_and_overrides_keywords() -> None:
    def collect(*args: int, **kw: int) -> tuple[tuple[int, ...], dict[str, int]]:
        """Return what it was called with."""
        return args, kw

    async def acollect(*args: int) -> tuple[int, ...]:
        """Return the arguments, asynchronously."""
        return args

    call = DeferredCall(collect, (1,), {"a": 1, "b": 2})
    assert await call.run(2, b=3) == ((1, 2), {"a": 1, "b": 3})
    assert await DeferredCall(acollect).run(5) == (5,)


async def test_delayed_callback_runs_after_the_delay() -> None:
    finished: list[DelayedCallback[int]] = []

    async def on_finished(cb: DelayedCallback[int]) -> None:
        """Record the finished callback."""
        finished.append(cb)

    cb = DelayedCallback(0.01, lambda x: x * 2, (4,), on_finished=on_finished)
    assert not cb.started and cb.task is None and not cb.done
    task = cb.start()
    assert cb.start() is task and cb.started
    assert await task == 8
    assert cb.done and cb.callback_started and not cb.cancelled
    assert finished == [cb]


async def test_delayed_callback_cancelled_during_the_delay_never_runs() -> None:
    ran: list[int] = []
    cb = DelayedCallback(10, ran.append, (1,))

    await cb.cancel()
    cb.start()
    await asyncio.sleep(0)
    await cb.cancel()

    assert cb.cancelled and not cb.started
    assert not ran and not cb.callback_started


async def test_delayed_callback_waits_for_a_started_callback_unless_forced() -> None:
    running = asyncio.Event()

    async def slow() -> str:
        """Signal that it started, then take a moment."""
        running.set()
        await asyncio.sleep(0.05)
        return "done"

    cb = DelayedCallback(0, slow)
    task = cb.start()
    await running.wait()
    await cb.cancel()
    assert task.result() == "done"

    running.clear()
    forced = DelayedCallback(0, slow)
    task = forced.start()
    await running.wait()
    await forced.cancel(force=True)
    assert task.cancelled()


async def test_delayed_callback_wait_returns_none_when_cancelled() -> None:
    cb = DelayedCallback(10, print)
    cb.cancel_event.set()
    assert await cb.wait() is None


async def test_delayed_callback_cancel_after_it_finished_only_clears_the_task() -> None:
    cb = DelayedCallback(0, lambda: 1)
    task = cb.start()
    assert await task == 1

    await cb.cancel()
    assert cb.task is None and cb.cancelled
    assert task.result() == 1 and not task.cancelled()


async def test_delayed_callback_an_on_finished_error_never_hides_the_callbacks_own() -> None:
    def fail() -> None:
        """Fail as the callback."""
        msg = "the callback's own"
        raise ValueError(msg)

    def broken_on_finished(cb: DelayedCallback[None]) -> None:
        """Fail as the hook."""
        msg = "the hook's"
        raise RuntimeError(msg)

    cb = DelayedCallback(0, fail, on_finished=broken_on_finished)

    with pytest.raises(ValueError, match="the callback's own"):
        await cb.start()


class SpyExecutor(ThreadPoolExecutor):
    """A thread pool that counts the calls submitted to it."""

    def __init__(self) -> None:
        """Start with no submissions."""
        super().__init__(max_workers=1)
        self.submitted = 0

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Any:
        """Count the call, then submit it."""
        self.submitted += 1
        return super().submit(fn, *args, **kwargs)


def test_deferred_call_always_runs_on_a_success_too() -> None:
    assert DeferredCall(print, when=TriggerOn.ALWAYS).should_run(1)


async def test_deferred_call_runs_a_sync_func_in_the_given_executor() -> None:
    with SpyExecutor() as executor:
        thread = await DeferredCall(threading.get_ident).run(executor=executor)

    assert executor.submitted == 1 and thread != threading.get_ident()


async def test_deferred_call_awaits_an_awaitable_given_as_func() -> None:
    assert await DeferredCall(asyncio.sleep(0, result=5)).run() == 5


async def test_delayed_callback_awaits_an_awaitable_given_as_callback() -> None:
    assert await DelayedCallback(0, asyncio.sleep(0, result=6)).start() == 6


async def test_delayed_callback_runs_sync_callables_in_a_worker_thread() -> None:
    threads: list[int] = []

    def on_finished(cb: DelayedCallback[int]) -> None:
        """Record the thread the hook runs in."""
        threads.append(threading.get_ident())

    cb = DelayedCallback(0, threading.get_ident, on_finished=on_finished)
    callback_thread = await cb.start()

    assert threading.get_ident() not in (callback_thread, *threads) and len(threads) == 1


async def test_delayed_callback_calls_on_finished_when_cancelled() -> None:
    finished: list[DelayedCallback[None]] = []
    cb = DelayedCallback(10, print, on_finished=finished.append)

    cb.start()
    await asyncio.sleep(0)
    await cb.cancel()

    assert finished == [cb] and not cb.callback_started


async def test_delayed_callback_logs_an_on_finished_error(caplog: pytest.LogCaptureFixture) -> None:
    def broken_on_finished(cb: DelayedCallback[int]) -> None:
        """Fail as the hook."""
        msg = "the hook failed"
        raise RuntimeError(msg)

    with caplog.at_level(logging.ERROR):
        assert await DelayedCallback(0, lambda: 1, on_finished=broken_on_finished).start() == 1

    assert "the hook failed" in caplog.text


async def test_delayed_callback_cancelled_before_start_never_runs() -> None:
    ran: list[int] = []
    cb = DelayedCallback(0.01, ran.append, (1,))

    await cb.cancel()
    assert cb.cancelled and not cb.started

    assert await cb.start() is None
    await asyncio.sleep(0.05)
    assert not ran and not cb.callback_started


async def test_delayed_callback_cancel_raises_a_started_callbacks_error() -> None:
    running = asyncio.Event()

    async def fail_later() -> None:
        """Signal that it started, then fail."""
        running.set()
        await asyncio.sleep(0.01)
        msg = "the callback failed"
        raise ValueError(msg)

    cb = DelayedCallback(0, fail_later)
    cb.start()
    await running.wait()

    with pytest.raises(ValueError, match="the callback failed"):
        await cb.cancel()


async def test_delayed_callback_error_carries_no_timeout_context() -> None:
    def fail() -> None:
        """Fail as the callback."""
        msg = "the callback's own"
        raise ValueError(msg)

    with pytest.raises(ValueError, match="the callback's own") as info:
        await DelayedCallback(0, fail).start()

    assert not isinstance(info.value.__context__, asyncio.TimeoutError)
    assert info.value.__context__ is None


async def test_delayed_callback_start_after_a_natural_finish_returns_the_same_task() -> None:
    cb = DelayedCallback(0, lambda: 1)
    task = cb.start()
    assert await task == 1

    assert cb.done and cb.started
    assert cb.start() is task and cb.done
