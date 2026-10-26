from __future__ import annotations as _annotations

import asyncio
import inspect
import threading
from typing import TYPE_CHECKING

import pytest

from pytrove.async_tools._internal import _LoopWork

if TYPE_CHECKING:
    from collections.abc import Awaitable


def _work(concurrency: int = 0) -> _LoopWork:
    """Return loop state on the running test loop."""
    return _LoopWork(asyncio.get_running_loop(), concurrency)


async def test_loop_work_starts_empty_on_its_loop() -> None:
    work = _work()

    assert work.loop is asyncio.get_running_loop()
    assert work.tasks == set()
    assert work.slots is None
    assert not work.drain.is_set()
    assert not work.closed


@pytest.mark.parametrize("concurrency", [0, -1])
async def test_concurrency_of_zero_or_less_means_no_cap(concurrency: int) -> None:
    assert _work(concurrency).slots is None


async def test_a_positive_concurrency_caps_with_a_semaphore() -> None:
    work = _work(2)

    assert work.slots is not None
    await work.slots.acquire()
    await work.slots.acquire()
    assert work.slots.locked()


async def test_run_registers_and_bounds_the_task() -> None:
    work = _work(1)

    async def probe() -> int:
        """Report how many tasks are tracked while it runs."""
        return len(work.tasks)

    assert await work.run(probe, (), {}) == 1
    assert not work.tasks
    assert work.slots is not None
    assert not work.slots.locked()


async def test_run_rejects_a_non_awaitable_and_cleans_up() -> None:
    work = _work(1)

    with pytest.raises(TypeError, match="awaitable"):
        await work.run(lambda: None, (), {})

    assert not work.tasks
    assert work.slots is not None
    assert not work.slots.locked()


async def test_run_cleans_up_when_func_raises_synchronously() -> None:
    work = _work(1)

    def boom() -> None:
        """Fail before returning an awaitable."""
        raise KeyError

    with pytest.raises(KeyError):
        await work.run(boom, (), {})

    assert not work.tasks
    assert work.slots is not None
    assert not work.slots.locked()


async def test_run_releases_the_slot_when_the_work_raises() -> None:
    work = _work(1)

    async def boom() -> None:
        """Fail while running."""
        raise ValueError

    with pytest.raises(ValueError):  # noqa: PT011 - the work raises a bare `ValueError`
        await work.run(boom, (), {})

    assert not work.tasks
    assert work.slots is not None
    assert not work.slots.locked()


async def test_run_releases_the_slot_even_when_cancelled() -> None:
    work = _work(1)

    async def hang() -> None:
        """Wait until cancelled."""
        await asyncio.Event().wait()

    task = asyncio.ensure_future(work.run(hang, (), {}))
    await asyncio.sleep(0)
    assert work.slots is not None
    assert work.slots.locked()
    assert task in work.tasks

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert not work.slots.locked()
    assert not work.tasks


async def test_run_parked_on_a_full_cap_never_calls_func() -> None:
    work = _work(1)
    calls: list[int] = []

    def job() -> Awaitable[None]:
        """Count the call."""
        calls.append(1)
        return asyncio.sleep(0)

    assert work.slots is not None
    await work.slots.acquire()
    task = asyncio.ensure_future(work.run(job, (), {}))
    await asyncio.sleep(0)
    assert task in work.tasks  # Registered while parked, so a drain sees it.

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert calls == []  # No coroutine was created, so none is left unawaited.
    assert not work.tasks
    work.slots.release()


async def test_run_refuses_once_closed_without_calling_func() -> None:
    work = _work()
    work.closed = True
    called: list[bool] = []

    async def job() -> None:
        """Record that it ran."""
        called.append(True)

    with pytest.raises(asyncio.CancelledError):
        await asyncio.create_task(work.run(job, (), {}))

    assert called == []
    assert not work.tasks


async def test_run_nested_in_a_tracked_task_keeps_it_tracked() -> None:
    work = _work()
    seen: list[bool] = []

    async def inner() -> None:
        """Do nothing."""

    async def outer() -> None:
        """Run a nested tracked call, then check that this task is still tracked."""
        await work.run(inner, (), {})
        seen.append(asyncio.current_task() in work.tasks)

    await work.run(outer, (), {})
    assert seen == [True]
    assert not work.tasks


async def test_wait_drained_sleeps_until_a_drain_is_requested() -> None:
    work = _work()
    drained = asyncio.ensure_future(work.wait_drained())
    await asyncio.sleep(0.01)
    assert not drained.done()

    work.drain.set()
    await asyncio.wait_for(drained, 5)


async def test_wait_drained_closes_the_work_once_the_drain_starts() -> None:
    work = _work()
    drained = asyncio.ensure_future(work.wait_drained())
    await asyncio.sleep(0)
    assert not work.closed

    work.drain.set()
    await asyncio.wait_for(drained, 5)
    assert work.closed


async def test_wait_drained_waits_for_started_work_and_refuses_what_starts_later() -> None:
    work = _work()
    finished: list[str] = []
    late: list[asyncio.Task[None]] = []

    async def job() -> None:
        """Record that it ran."""
        finished.append("late")

    async def spawn() -> None:
        """Start another submission once the drain has begun, then finish."""
        await asyncio.sleep(0.02)
        late.append(asyncio.ensure_future(work.run(job, (), {})))
        finished.append("spawn")

    asyncio.ensure_future(work.run(spawn, (), {}))
    await asyncio.sleep(0)
    work.drain.set()
    await asyncio.wait_for(work.wait_drained(), 5)

    with pytest.raises(asyncio.CancelledError):
        await late[0]

    assert finished == ["spawn"]  # Started before the drain: waited for; after it: never ran.


async def test_run_nested_under_a_cap_runs_inside_the_outer_slot() -> None:
    work = _work(1)

    async def inner() -> str:
        """Return at once."""
        return "inner"

    async def outer() -> str:
        """Hold the only slot and nest a call, which must not wait for a second one."""
        return await work.run(inner, (), {})

    assert await asyncio.wait_for(work.run(outer, (), {}), 5) == "inner"
    assert work.slots is not None
    assert not work.slots.locked()


async def test_schedule_runs_the_coroutine_and_hands_back_its_result() -> None:
    work = _work()
    fut = await asyncio.to_thread(work.schedule, asyncio.sleep(0, result=3))

    assert await asyncio.wait_for(asyncio.wrap_future(fut), 5) == 3


async def test_schedule_hands_back_what_the_coroutine_raises() -> None:
    work = _work()

    async def boom() -> None:
        """Fail."""
        raise KeyError

    fut = await asyncio.to_thread(work.schedule, boom())

    with pytest.raises(KeyError):
        await asyncio.wait_for(asyncio.wrap_future(fut), 5)


async def test_schedule_cancels_the_future_when_the_task_is_cancelled() -> None:
    work = _work()

    async def cancel_self() -> None:
        """Get cancelled from inside."""
        raise asyncio.CancelledError

    fut = await asyncio.to_thread(work.schedule, cancel_self())

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(asyncio.wrap_future(fut), 5)

    assert fut.cancelled()


async def test_schedule_cancels_the_task_when_the_future_is_cancelled() -> None:
    work = _work()
    started = asyncio.Event()
    ended: list[str] = []

    async def hang() -> None:
        """Wait until cancelled."""
        started.set()

        try:
            await asyncio.Event().wait()
        finally:
            ended.append("cancelled")

    fut = await asyncio.to_thread(work.schedule, hang())
    await asyncio.wait_for(started.wait(), 5)
    await asyncio.to_thread(fut.cancel)

    for _ in range(100):
        if ended:
            break

        await asyncio.sleep(0)

    assert ended == ["cancelled"]


async def test_schedule_creates_no_task_once_the_work_is_closed() -> None:
    work = _work()
    work.closed = True
    coro = asyncio.sleep(0)
    before = asyncio.all_tasks()
    fut = await asyncio.to_thread(work.schedule, coro)

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(asyncio.wrap_future(fut), 5)

    assert asyncio.all_tasks() <= before | {asyncio.current_task()}
    assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED  # Never warns unawaited.


async def test_schedule_creates_no_task_for_a_future_cancelled_before_it_started() -> None:
    work = _work()
    coro = asyncio.sleep(0)
    fut = work.schedule(coro)  # Its start is queued on this loop and has not run yet.
    fut.cancel()
    await asyncio.sleep(0)

    assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED


def test_schedule_refuses_a_closed_loop() -> None:
    loop = asyncio.new_event_loop()
    work = _LoopWork(loop, 0)
    loop.close()
    coro = asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="closed"):
        work.schedule(coro)

    coro.close()  # The caller closes it, as `_LoopHost._schedule` does.


async def test_request_drain_works_from_another_thread() -> None:
    work = _work()
    thread = threading.Thread(target=work.request_drain)
    thread.start()
    thread.join(5)

    await asyncio.wait_for(work.wait_drained(), 5)
    assert work.drain.is_set()


def test_request_drain_refuses_a_closed_loop() -> None:
    loop = asyncio.new_event_loop()
    work = _LoopWork(loop, 0)
    loop.close()

    with pytest.raises(RuntimeError, match="closed"):
        work.request_drain()
