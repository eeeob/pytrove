from __future__ import annotations as _annotations

import asyncio
import sys
import threading

import pytest

from pytrove.async_tools import AioThreadWorker

from pytrove.object_tools.proxies import HAS_WRAPT

needs_proxy = pytest.mark.skipif(not HAS_WRAPT, reason="needs the proxy extra")


async def _thread_id() -> int:
    """Return the id of the thread this runs on."""
    return threading.get_ident()


@needs_proxy
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

    with pytest.raises(RuntimeError, match="finished"):
        worker.run()


@needs_proxy
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


@needs_proxy
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


async def test_awaiting_the_worker_joins_it() -> None:
    worker = AioThreadWorker()
    await worker

    assert worker.is_stopping()
    assert worker.is_finished()


@pytest.mark.skipif(HAS_WRAPT, reason="checks the error raised without the proxy extra")
async def test_submit_without_the_proxy_extra_names_it() -> None:
    async with AioThreadWorker() as worker:
        with pytest.raises(ImportError, match=r"pytrove\[proxy\]"):
            await worker.submit(_thread_id)


@needs_proxy
async def test_join_refuses_the_workers_own_thread() -> None:
    async with AioThreadWorker() as worker:

        async def join_from_inside() -> None:
            """Join the worker from its own loop."""
            await worker.join()

        with pytest.raises(RuntimeError, match="from inside the worker's own thread"):
            await worker.submit(join_from_inside)


@needs_proxy
async def test_join_lets_in_flight_work_finish() -> None:
    worker = AioThreadWorker()
    worker.wait_for_running(5)
    work = asyncio.ensure_future(worker.submit(asyncio.sleep, 0.05, result=7))
    await asyncio.sleep(0.01)
    await worker.join(timeout=5)

    assert await work == 7


@needs_proxy
async def test_join_times_out_while_work_is_still_running() -> None:
    worker = AioThreadWorker()
    worker.wait_for_running(5)
    work = asyncio.ensure_future(worker.submit(asyncio.sleep, 0.3))
    await asyncio.sleep(0.01)

    with pytest.raises(TimeoutError, match="did not stop within 0.01"):
        await worker.join(timeout=0.01)

    await worker.join(timeout=5)
    await work
    assert worker.is_finished()


@needs_proxy
async def test_submit_refuses_new_work_while_stopping() -> None:
    worker = AioThreadWorker()
    worker.wait_for_running(5)
    work = asyncio.ensure_future(worker.submit(asyncio.sleep, 0.05))
    await asyncio.sleep(0.01)
    joining = asyncio.ensure_future(worker.join(timeout=5))
    await asyncio.sleep(0.01)

    assert worker.is_running()

    with pytest.raises(RuntimeError, match="worker is stopping"):
        await worker.submit(_thread_id)

    await joining
    await work


@needs_proxy
async def test_submit_from_the_workers_own_loop_runs_inline() -> None:
    async with AioThreadWorker() as worker:

        async def nested() -> int:
            """Submit from inside the worker's loop."""
            return await worker.submit(_thread_id)

        async def outer() -> tuple[int, int]:
            """Report this thread and the one the nested submission ran on."""
            return threading.get_ident(), await nested()

        own, inner = await worker.submit(outer)

    assert own == inner


@needs_proxy
async def test_cancelling_the_caller_cancels_the_submission() -> None:
    started = threading.Event()
    cancelled = threading.Event()

    async def hang() -> None:
        """Wait until cancelled, recording both moments."""
        started.set()

        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async with AioThreadWorker() as worker:
        caller = asyncio.ensure_future(worker.submit(hang))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        caller.cancel()

        with pytest.raises(asyncio.CancelledError):
            await caller

        assert await asyncio.get_running_loop().run_in_executor(None, cancelled.wait, 5)


@needs_proxy
async def test_work_cancelling_itself_while_the_worker_runs_stays_a_cancellation() -> None:
    async def cancel_self() -> None:
        """Raise a cancellation nobody asked the caller for."""
        raise asyncio.CancelledError

    async with AioThreadWorker() as worker:
        with pytest.raises(asyncio.CancelledError):
            await worker.submit(cancel_self)


@needs_proxy
async def test_work_cancelled_by_a_stopping_worker_reports_the_stop() -> None:
    async def cancelled_late() -> None:
        """Get cancelled once the worker has begun stopping."""
        await asyncio.sleep(0.05)
        raise asyncio.CancelledError

    worker = AioThreadWorker()
    worker.wait_for_running(5)
    work = asyncio.ensure_future(worker.submit(cancelled_late))
    await asyncio.sleep(0.01)
    joining = asyncio.ensure_future(worker.join(timeout=5))

    if sys.version_info >= (3, 11):
        with pytest.raises(RuntimeError, match="stopped before this task completed"):
            await work
    else:  # `Task.cancelling` is new in 3.11; without it the cancellation is passed on as is.
        with pytest.raises(asyncio.CancelledError):
            await work

    await joining
