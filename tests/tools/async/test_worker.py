from __future__ import annotations as _annotations

import asyncio
import sys
import threading
import time
from typing import Any, TYPE_CHECKING

import pytest

from pytrove.async_tools import AioThreadWorker
from pytrove.async_tools._internal import loop_host
from pytrove.object_tools.proxies import HAS_WRAPT

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

needs_proxy = pytest.mark.skipif(not HAS_WRAPT, reason="needs the proxy extra")


async def _thread_id() -> int:
    """Return the id of the thread this runs on."""
    return threading.get_ident()


def _patch_run_loop(
    monkeypatch: pytest.MonkeyPatch,
    run_loop: Callable[
        [Coroutine[Any, Any, Any], Callable[[], asyncio.AbstractEventLoop] | None], None
    ],
) -> None:
    """Replace the loop driver the worker thread calls."""
    monkeypatch.setattr(loop_host, "_run_loop", run_loop)


def _block_until_finished(worker: AioThreadWorker) -> None:
    """Block the calling thread, and so its loop, until the worker's thread ended."""
    deadline = time.monotonic() + 5

    while not worker.is_finished() and time.monotonic() < deadline:
        time.sleep(0.001)


async def test_worker_runs_work_on_its_own_named_thread() -> None:
    async with AioThreadWorker(name="w") as worker:
        assert worker.is_running()
        assert worker._lifecycle.thread is not None
        assert worker._lifecycle.thread.name == "w"
        assert await worker.submit(_thread_id) != threading.get_ident()
        assert await worker(asyncio.sleep, 0, result=5) == 5

    assert worker.is_finished()
    assert worker.is_stopping()


async def test_submit_needs_no_optional_extra() -> None:
    async with AioThreadWorker() as worker:
        assert await worker.submit(asyncio.sleep, 0, result=2) == 2


async def test_submit_passes_on_what_the_work_raises() -> None:
    async def boom() -> None:
        """Fail."""
        msg = "k"
        raise KeyError(msg)

    async with AioThreadWorker() as worker:
        with pytest.raises(KeyError, match="k"):
            await worker.submit(boom)


@needs_proxy
def test_get_loop_hands_out_the_loop_without_stop_or_close() -> None:
    worker = AioThreadWorker()
    worker.wait_for_running(5)
    loop = worker.get_loop()

    assert loop.is_running()
    assert worker.get_loop() is loop  # The proxy is built once.

    with pytest.raises(AttributeError):
        loop.close()

    with pytest.raises(AttributeError):
        loop.stop()

    asyncio.run(worker.join(timeout=5))


def test_get_loop_refuses_a_worker_that_is_not_running() -> None:
    worker = AioThreadWorker(run_now=False)

    with pytest.raises(RuntimeError, match="not been started"):
        worker.get_loop()


def test_loop_proxy_refuses_before_the_loop_is_published() -> None:
    worker = AioThreadWorker(run_now=False)

    with pytest.raises(RuntimeError, match="not been published"):
        _ = worker._loop_proxy


@pytest.mark.skipif(HAS_WRAPT, reason="checks the error raised without the proxy extra")
def test_get_loop_without_the_proxy_extra_names_it() -> None:
    worker = AioThreadWorker()
    worker.wait_for_running(5)

    with pytest.raises(ImportError, match=r"pytrove\[proxy\]"):
        worker.get_loop()

    asyncio.run(worker.join(timeout=5))


async def test_worker_refuses_work_after_join() -> None:
    worker = AioThreadWorker()
    await worker.join()

    with pytest.raises(RuntimeError, match="worker is closed"):
        await worker.submit(_thread_id)

    with pytest.raises(RuntimeError, match="finished"):
        worker.run()


async def test_submit_on_a_worker_never_started_says_so() -> None:
    worker = AioThreadWorker(run_now=False)

    with pytest.raises(RuntimeError, match="not been started"):
        await worker.submit(_thread_id)


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

    with pytest.raises(RuntimeError, match="starts it only once"):
        worker.run()  # One shot, even while the thread is alive.

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

    async def join_twice() -> list[BaseException | None]:
        """Join, then join again once the thread has ended."""
        return [await worker.join(timeout=5), await worker.join(timeout=5)]

    assert asyncio.run(join_twice()) == [None, None]
    assert worker.is_finished()


async def test_worker_join_is_safe_to_call_concurrently() -> None:
    worker = AioThreadWorker()
    worker.wait_for_running(5)
    work = asyncio.ensure_future(worker.submit(asyncio.sleep, 0.05, result=1))
    await asyncio.sleep(0.01)

    await asyncio.gather(worker.join(timeout=5), worker.join(timeout=5))

    assert worker.is_finished()
    assert await work == 1


async def test_join_after_a_startup_death_returns_the_death(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def run_loop(
        coro: Coroutine[Any, Any, Any], _factory: Callable[[], asyncio.AbstractEventLoop] | None
    ) -> None:
        """Fail before the loop ever runs."""
        coro.close()
        msg = "no loop"
        raise OSError(msg)

    _patch_run_loop(monkeypatch, run_loop)
    worker = AioThreadWorker()
    death = await worker.join(timeout=5)

    assert isinstance(death, OSError)
    assert await worker is death  # The same, every time.
    assert worker.is_finished()
    assert not caplog.records  # Returned, never logged.


async def test_join_after_the_loop_died_while_running_returns_the_death() -> None:
    async def stop_loop() -> None:
        """Stop the worker's loop from inside, which ends its thread."""
        asyncio.get_running_loop().stop()

    worker = AioThreadWorker()
    await asyncio.to_thread(worker.wait_for_running, 5)
    fut = worker._schedule(stop_loop, (), {})
    await asyncio.wrap_future(fut)

    assert isinstance(await worker.join(timeout=5), RuntimeError)
    assert worker.is_finished()


async def test_a_submission_lost_with_a_dying_loop_fails_instead_of_hanging() -> None:
    async def stop_loop() -> None:
        """Stop the worker's loop from inside, which ends its thread."""
        asyncio.get_running_loop().stop()

    worker = AioThreadWorker()
    await asyncio.to_thread(worker.wait_for_running, 5)
    hung = asyncio.ensure_future(worker.submit(asyncio.sleep, 10))
    await asyncio.sleep(0.01)
    await worker.submit(stop_loop)

    # The teardown cancels it while the flags may still read "running", so either error is
    # possible; what matters is that it fails instead of hanging.
    with pytest.raises((RuntimeError, asyncio.CancelledError)):
        await asyncio.wait_for(asyncio.shield(hung), 5)

    await worker.join(timeout=5)


async def test_awaiting_the_worker_joins_it() -> None:
    worker = AioThreadWorker()
    await worker

    assert worker.is_stopping()
    assert worker.is_finished()


async def test_entering_does_not_block_the_calling_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    real_run_loop = loop_host._run_loop

    def slow_run_loop(
        coro: Coroutine[Any, Any, Any], factory: Callable[[], asyncio.AbstractEventLoop] | None
    ) -> None:
        """Start the loop only after a while."""
        threading.Event().wait(0.1)
        real_run_loop(coro, factory)

    _patch_run_loop(monkeypatch, slow_run_loop)
    ticks = 0

    async def tick() -> None:
        """Count loop iterations until cancelled."""
        nonlocal ticks

        while True:
            ticks += 1
            await asyncio.sleep(0.005)

    ticker = asyncio.ensure_future(tick())
    await asyncio.sleep(0)
    ticks = 0

    async with AioThreadWorker():
        assert ticks > 1

    ticker.cancel()


async def test_entering_a_stopped_worker_raises() -> None:
    worker = AioThreadWorker(run_now=False)
    await worker.join()

    with pytest.raises(RuntimeError, match="already been asked to stop"):
        async with worker:
            pass


async def test_exiting_does_not_suppress_the_error() -> None:
    with pytest.raises(KeyError):
        async with AioThreadWorker() as worker:
            raise KeyError

    assert worker.is_finished()


async def test_join_refuses_the_workers_own_thread() -> None:
    async with AioThreadWorker() as worker:

        async def join_from_inside() -> None:
            """Join the worker from its own loop."""
            await worker.join()

        with pytest.raises(RuntimeError, match="from inside the worker's own thread"):
            await worker.submit(join_from_inside)


async def test_join_lets_in_flight_work_finish() -> None:
    worker = AioThreadWorker()
    worker.wait_for_running(5)
    work = asyncio.ensure_future(worker.submit(asyncio.sleep, 0.05, result=7))
    await asyncio.sleep(0.01)
    await worker.join(timeout=5)

    assert await work == 7


async def test_join_lets_a_submission_with_a_nested_submit_finish() -> None:
    worker = AioThreadWorker()
    worker.wait_for_running(5)
    nested_done = threading.Event()

    async def outer() -> str:
        """Submit inline from the worker's loop, then keep running."""
        await worker.submit(asyncio.sleep, 0)
        nested_done.set()
        await asyncio.sleep(0.1)
        return "done"

    work = asyncio.ensure_future(worker.submit(outer))
    assert await asyncio.to_thread(nested_done.wait, 5)
    await worker.join(timeout=5)

    assert await work == "done"


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


async def test_nested_submit_while_stopping_is_refused() -> None:
    worker = AioThreadWorker()
    worker.wait_for_running(5)
    seen: list[BaseException] = []

    async def outer() -> None:
        """Submit again from the worker's loop once it is stopping."""
        await asyncio.sleep(0.05)

        try:
            await worker.submit(asyncio.sleep, 0)
        except RuntimeError as e:
            seen.append(e)

    work = asyncio.ensure_future(worker.submit(outer))
    await asyncio.sleep(0.01)
    await worker.join(timeout=5)
    await work

    assert "worker is stopping" in str(seen[0])


async def test_nested_submit_under_a_cap_does_not_deadlock() -> None:
    async with AioThreadWorker(concurrency=1) as worker:

        async def outer() -> int:
            """Hold the only slot and submit again from the worker's loop."""
            return await worker.submit(_thread_id)

        assert await asyncio.wait_for(worker.submit(outer), 5) == await worker.submit(_thread_id)


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


async def test_work_cancelling_itself_while_the_worker_runs_stays_a_cancellation() -> None:
    async def cancel_self() -> None:
        """Raise a cancellation nobody asked the caller for."""
        raise asyncio.CancelledError

    async with AioThreadWorker() as worker:
        with pytest.raises(asyncio.CancelledError):
            await worker.submit(cancel_self)


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

    with pytest.raises(RuntimeError, match="stopped before this task completed"):
        await work

    await joining


@pytest.mark.skipif(sys.version_info < (3, 11), reason="`Task.cancelling` arrived in 3.11")
async def test_caller_cancelled_after_the_stop_cancelled_the_work_stays_cancelled() -> None:
    async def cancelled_once_stopping() -> None:
        """Get cancelled as soon as the worker has begun stopping."""
        while not worker.is_stopping():
            await asyncio.sleep(0.001)

        raise asyncio.CancelledError

    worker = AioThreadWorker()
    worker.wait_for_running(5)
    caller = asyncio.ensure_future(worker.submit(cancelled_once_stopping))
    joining = asyncio.ensure_future(worker.join(timeout=5))
    await asyncio.sleep(0)  # `caller` awaits the shield, `joining` has started the stop.
    _block_until_finished(worker)  # The work's cancellation now waits in this loop's queue.

    # Step until the shield is done but `caller` has not woken yet (`_fut_waiter` is the
    # future a task waits on), then cancel it in that gap.
    for _ in range(100):
        waiter = caller._fut_waiter

        if waiter is not None and waiter.done():
            break

        await asyncio.sleep(0)

    assert caller.cancel()

    with pytest.raises(asyncio.CancelledError):
        await caller

    await joining


async def test_entering_a_worker_started_by_run_now_does_not_run_it_again() -> None:
    worker = AioThreadWorker()  # `run_now` used the one start already.

    async with worker:
        assert await worker.submit(asyncio.sleep, 0, result=6) == 6


async def test_entering_a_finished_worker_raises() -> None:
    worker = AioThreadWorker()
    await worker.join(timeout=5)

    with pytest.raises(RuntimeError, match="finished"):
        async with worker:
            pass


async def test_exiting_never_raises_the_death(monkeypatch: pytest.MonkeyPatch) -> None:
    def run_loop(
        coro: Coroutine[Any, Any, Any], _factory: Callable[[], asyncio.AbstractEventLoop] | None
    ) -> None:
        """Fail before the loop ever runs."""
        coro.close()
        msg = "no loop"
        raise OSError(msg)

    _patch_run_loop(monkeypatch, run_loop)
    worker = AioThreadWorker()

    with pytest.raises(RuntimeError, match="its thread ended|finished"):  # Before or after it died.
        async with worker:
            pass

    await worker.__aexit__(None, None, None)  # Joining a dead worker returns; it never raises.
    assert isinstance(await worker.join(), OSError)
