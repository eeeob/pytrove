from __future__ import annotations as _annotations

import asyncio

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
