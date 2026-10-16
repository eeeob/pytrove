from __future__ import annotations as _annotations

import asyncio
import sys
import threading
import warnings

import pytest

from pytrove.async_tools import AioThreadWorker, SyncAwaitableRunner
from pytrove.async_tools._threads import _check_loop_factory, _run_loop, _run_tracked


async def _thread_id() -> int:
    """Return the id of the thread this runs on."""
    return threading.get_ident()


async def test_worker_runs_work_on_its_own_thread() -> None:
    async with AioThreadWorker(name="w") as worker:
        assert worker.is_running()
        assert await worker.submit(_thread_id) != threading.get_ident()
        assert await worker(asyncio.sleep, 0, result=5) == 5
        loop = worker.get_loop()

        with pytest.raises(AttributeError):
            loop.stop()

    assert worker.is_finished()
    assert worker.is_stopping()


async def test_worker_refuses_work_after_join() -> None:
    worker = AioThreadWorker()
    await worker.join()

    with pytest.raises(RuntimeError, match="closed|stopping"):
        await worker.submit(_thread_id)

    with pytest.raises(RuntimeError):
        worker.run()


async def test_worker_caps_concurrency() -> None:
    running = 0
    peak = 0

    async def job() -> None:
        """Track how many jobs overlap."""
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1

    async with AioThreadWorker(concurrency=2) as worker:
        await asyncio.gather(*(worker.submit(job) for _ in range(6)))

    assert peak == 2


async def test_worker_rejects_a_non_awaitable_function() -> None:
    async with AioThreadWorker() as worker:
        with pytest.raises(TypeError, match="awaitable"):
            await worker.submit(lambda: 1)


def test_worker_lifecycle_without_a_loop() -> None:
    worker = AioThreadWorker(run_now=False)
    assert not worker.is_started()

    with pytest.raises(RuntimeError, match="not been started"):
        worker.wait_for_running()

    worker.run(wait=5)
    assert worker.is_running()
    asyncio.run(worker.join(timeout=5))
    assert not worker.is_running()


def test_worker_is_finished_only_after_its_thread_ended() -> None:
    worker = AioThreadWorker(run_now=False)
    assert not worker.is_finished()

    worker.run(wait=5)
    assert not worker.is_finished()
    worker.run()  # A no-op while the thread is alive.

    asyncio.run(worker.join(timeout=5))
    assert worker.is_finished()

    with pytest.raises(RuntimeError, match="finished"):
        worker.run()


def test_worker_join_before_start_prevents_any_start() -> None:
    worker = AioThreadWorker(run_now=False)
    asyncio.run(worker.join())

    assert worker.is_stopping()
    assert not worker.is_started()

    with pytest.raises(RuntimeError, match="already been asked to stop"):
        worker.run()


def test_worker_join_is_safe_to_repeat() -> None:
    worker = AioThreadWorker()

    async def join_twice() -> None:
        """Join, then join again once the thread has ended."""
        await worker.join(timeout=5)
        await worker.join(timeout=5)

    asyncio.run(join_twice())
    assert worker.is_finished()


def test_worker_validates_its_arguments() -> None:
    with pytest.raises(TypeError, match="concurrency"):
        AioThreadWorker(concurrency="2", run_now=False)

    with pytest.raises(TypeError, match="exception_handler"):
        AioThreadWorker(exception_handler=5, run_now=False)


def test_runner_keeps_one_loop_across_calls() -> None:
    with SyncAwaitableRunner(name="r") as runner:
        first = runner.run(_thread_id())
        assert runner(_thread_id()) == first
        assert runner.running

    assert runner.closed
    assert not runner.running

    with pytest.raises(RuntimeError):
        runner.run(_thread_id())


def test_lazy_runner_starts_on_first_use() -> None:
    runner = SyncAwaitableRunner(lazy=True)
    assert not runner.started
    assert runner.run(asyncio.sleep(0, result=3)) == 3

    with pytest.raises(RuntimeError, match="already started"):
        runner.start()

    runner.close()
    runner.close()


def test_closing_a_never_started_runner_only_marks_it_closed() -> None:
    runner = SyncAwaitableRunner(lazy=True)
    runner.close()

    assert runner.closed
    assert not runner.started


def test_check_loop_factory() -> None:
    with pytest.raises(TypeError, match="loop_factory"):
        _check_loop_factory(5)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _check_loop_factory(asyncio.new_event_loop)

    assert bool(caught) is (sys.version_info < (3, 12))


def test_run_loop_drives_a_coroutine() -> None:
    seen: list[int] = []

    async def mark() -> None:
        """Record that it ran."""
        seen.append(1)

    _run_loop(mark(), None)
    assert seen == [1]


async def test_run_tracked_registers_and_bounds_the_task() -> None:
    tasks: set[asyncio.Task[object]] = set()
    slots = asyncio.Semaphore(1)

    async def probe() -> int:
        """Report how many tasks are tracked while it runs."""
        return len(tasks)

    assert await _run_tracked(probe, (), {}, tasks, slots) == 1
    assert not tasks
    assert await _run_tracked(probe, (), {}, None, None) == 0

    with pytest.raises(TypeError):
        await _run_tracked(lambda: None, (), {}, tasks, None)
