from __future__ import annotations as _annotations

import asyncio
import concurrent.futures
import contextlib
import gc
import inspect
import logging
import sys
import threading
from collections.abc import Callable, Coroutine, Iterator
from typing import Any

import pytest

from pytrove.async_tools import AioThreadWorker
from pytrove.async_tools._internal import _LoopHost, _LoopState, _LoopWork, loop_host

_LoopRunner = Callable[
    [Coroutine[Any, Any, Any], Callable[[], asyncio.AbstractEventLoop] | None], None
]


def _patch_run_loop(monkeypatch: pytest.MonkeyPatch, run_loop: _LoopRunner) -> None:
    """Replace the loop driver the worker thread calls."""
    monkeypatch.setattr(loop_host, "_run_loop", run_loop)


def _hold_startup(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    """Keep the next host thread in startup until the returned event is set."""
    release = threading.Event()

    def run_loop(
        coro: Coroutine[Any, Any, Any], _factory: Callable[[], asyncio.AbstractEventLoop] | None
    ) -> None:
        """Hold the thread in startup until released."""
        coro.close()
        release.wait(5)

    _patch_run_loop(monkeypatch, run_loop)
    return release


def _fail_startup(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    """Make the next host thread die before its loop ever runs."""

    def run_loop(
        coro: Coroutine[Any, Any, Any], _factory: Callable[[], asyncio.AbstractEventLoop] | None
    ) -> None:
        """Fail before the loop ever runs."""
        coro.close()
        raise exc

    _patch_run_loop(monkeypatch, run_loop)


def _refuse_thread_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `Thread.start` fail as the OS refusing a new thread would."""

    def refuse(_self: threading.Thread) -> None:
        """Refuse."""
        msg = "can't start new thread"
        raise RuntimeError(msg)

    monkeypatch.setattr(threading.Thread, "start", refuse)


def _running_host(**kwargs: Any) -> _LoopHost:
    """Return a host whose loop is up."""
    host = _LoopHost(**kwargs)
    host.wait_for_running(5)
    return host


def _published(host: _LoopHost) -> _LoopWork:
    """Return the host's published loop state."""
    work = host._state().work
    assert work is not None
    return work


def _host_thread(host: _LoopHost) -> threading.Thread:
    """Return the host's started thread."""
    thread = host._lifecycle.thread
    assert thread is not None
    return thread


@contextlib.contextmanager
def _swapped_state(host: _LoopHost, state: _LoopState) -> Iterator[None]:
    """Publish `state` in place of the host's own for the block, then restore it."""
    real = host._lifecycle.state
    host._lifecycle.state = state

    try:
        yield
    finally:
        host._lifecycle.state = real


async def _noop() -> None:
    """Do nothing."""


def test_loop_host_starts_in_a_known_state() -> None:
    host = _LoopHost(run_now=False)

    assert host._state() == _LoopState("new")
    assert not host.is_started()
    assert not host.is_running()
    assert not host.is_stopping()
    assert not host.is_finished()
    assert host._lifecycle.thread is None
    assert not host._pending


def test_loop_host_names_its_daemon_thread() -> None:
    host = _running_host(name="h")
    thread = _host_thread(host)

    assert thread.name == "h"
    assert thread.daemon
    host._stop(5)


def test_loop_host_publishes_its_work_while_running_only() -> None:
    host = _running_host()

    assert _published(host).loop.is_running()
    assert host._state().phase == "running"
    host._stop(5)
    assert host._state() == _LoopState("stopped")


def test_bootstrap_refuses_any_thread_but_the_hosts() -> None:
    host = _running_host()

    with pytest.raises(RuntimeError, match="worker thread"):
        host._bootstrap()

    host._stop(5)


def test_bootstrap_refuses_before_run_instead_of_blocking() -> None:
    host = _LoopHost(run_now=False)
    errors: list[BaseException] = []

    def call() -> None:
        """Call `_bootstrap` and keep what it raises."""
        try:
            host._bootstrap()
        except RuntimeError as e:
            errors.append(e)

    thread = threading.Thread(target=call, daemon=True)
    thread.start()
    thread.join(5)

    assert not thread.is_alive()
    assert len(errors) == 1


def test_bootstrap_unpublishes_before_it_sweeps() -> None:
    host = _running_host()
    seen: list[tuple[object, bool]] = []

    class _Watched(dict[Any, Any]):
        """A pending map that records the host's state when the sweep copies it."""

        def copy(self) -> dict[Any, Any]:
            """Record, then copy."""
            seen.append((host._state().work, host.is_running()))
            return dict(self)

    host._pending = _Watched()
    host._stop(5)

    assert seen == [(None, False)]


def test_bootstrap_keeps_a_keyboard_interrupt_and_lets_it_escape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    escaped: list[type[BaseException] | None] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: escaped.append(args.exc_type))
    _fail_startup(monkeypatch, KeyboardInterrupt())
    host = _LoopHost()

    death = host._stop(5)

    assert isinstance(death, KeyboardInterrupt)
    assert escaped == [KeyboardInterrupt]


def test_concurrency_reaches_the_loop_state() -> None:
    host = _running_host(concurrency=0)

    assert _published(host).slots is None
    host._stop(5)


def test_concurrency_true_reads_as_a_cap_of_one() -> None:
    host = _running_host(concurrency=True)
    running = 0
    peak = 0

    async def job() -> None:
        """Track how many jobs overlap."""
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1

    futures = [host._schedule(job, (), {}) for _ in range(3)]
    concurrent.futures.wait(futures, 5)
    host._stop(5)

    assert peak == 1


@pytest.mark.parametrize("concurrency", ["2", 2.0])
def test_concurrency_must_be_an_int(concurrency: object) -> None:
    with pytest.raises(TypeError, match="concurrency must be an int"):
        _LoopHost(concurrency=concurrency, run_now=False)


def test_exception_handler_must_be_callable() -> None:
    with pytest.raises(TypeError, match="exception_handler"):
        _LoopHost(exception_handler=5, run_now=False)


def test_exception_handler_receives_unhandled_loop_errors() -> None:
    seen: list[dict[str, Any]] = []
    called = threading.Event()

    def handler(_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        """Record the error context."""
        seen.append(context)
        called.set()

    def boom() -> None:
        """Fail inside a loop callback."""
        raise KeyError

    async def fail_in_a_callback() -> None:
        """Schedule a failing callback on the loop."""
        asyncio.get_running_loop().call_soon(boom)

    host = _running_host(exception_handler=handler)
    host._schedule(fail_in_a_callback, (), {}).result(5)

    assert called.wait(5)
    assert isinstance(seen[0]["exception"], KeyError)
    host._stop(5)


def test_host_closes_its_work_once_drained() -> None:
    host = _running_host()
    work = _published(host)

    assert not work.closed
    host._stop(5)
    assert work.closed


def test_checked_work_names_the_state_it_refuses() -> None:
    host = _LoopHost(run_now=False)

    with pytest.raises(RuntimeError, match="has not been started"):
        host._checked_work()

    host.run(wait=5)
    assert host._checked_work() is host._state().work
    host._stop(5)

    with pytest.raises(RuntimeError, match="worker is closed"):
        host._checked_work()


def test_checked_work_refuses_a_host_still_starting(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _hold_startup(monkeypatch)
    host = _LoopHost()

    try:
        with pytest.raises(RuntimeError, match="not running yet"):
            host._checked_work()
    finally:
        release.set()

    host._stop(5)


def test_checked_work_refuses_new_work_while_stopping_but_hands_out_the_loop() -> None:
    host = _running_host()
    work = _published(host)

    with _swapped_state(host, _LoopState("stopping", work)):
        with pytest.raises(RuntimeError, match="worker is stopping"):
            host._checked_work()

        assert host._checked_work(new_work=False) is work

    host._stop(5)


def test_checked_work_refuses_a_published_loop_that_is_not_running() -> None:
    host = _running_host()
    idle_loop = asyncio.new_event_loop()

    try:
        with (
            _swapped_state(host, _LoopState("running", _LoopWork(idle_loop, 0))),
            pytest.raises(RuntimeError, match="event loop is not running"),
        ):
            host._checked_work()
    finally:
        idle_loop.close()

    host._stop(5)


def test_checked_work_refuses_a_closed_loop() -> None:
    class _ClosedButRunning:
        """A loop stand-in that reports running and closed at once."""

        def is_running(self) -> bool:
            """Report running."""
            return True

        def is_closed(self) -> bool:
            """Report closed."""
            return True

    host = _running_host()
    fake_loop: Any = _ClosedButRunning()

    with (
        _swapped_state(host, _LoopState("running", _LoopWork(fake_loop, 0))),
        pytest.raises(RuntimeError, match="already closed"),
    ):
        host._checked_work()

    host._stop(5)


def test_on_own_loop_and_on_own_thread() -> None:
    host = _running_host()

    async def probe() -> tuple[bool, bool]:
        """Ask both questions from inside the host's loop."""
        return host._on_own_loop(), host._on_own_thread()

    assert not host._on_own_loop()
    assert not host._on_own_thread()
    assert host._schedule(probe, (), {}).result(5) == (True, True)
    host._stop(5)
    assert not host._on_own_loop()


def test_schedule_runs_tracked_work_and_forgets_it() -> None:
    host = _running_host()
    fut = host._schedule(asyncio.sleep, (0,), {"result": 3})

    assert fut.result(5) == 3
    assert not host._pending
    host._stop(5)


def test_schedule_refuses_a_stopping_host() -> None:
    host = _running_host()

    with (
        _swapped_state(host, _LoopState("stopping", _published(host))),
        pytest.raises(RuntimeError, match="worker is stopping"),
    ):
        host._schedule(asyncio.sleep, (0,), {})

    host._stop(5)


def test_schedule_does_not_take_the_lifecycle_lock() -> None:
    host = _running_host()
    futures: list[concurrent.futures.Future[Any]] = []

    with host._lifecycle._changed:  # Held as a lifecycle move would hold it.
        thread = threading.Thread(
            target=lambda: futures.append(host._schedule(asyncio.sleep, (0,), {"result": 1})),
            daemon=True,
        )
        thread.start()
        thread.join(2)
        finished = not thread.is_alive()

    thread.join(5)
    assert finished
    assert futures[0].result(5) == 1
    host._stop(5)


def test_schedule_cancels_a_future_published_after_the_loop_went(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _running_host()
    real_state = host._lifecycle.state
    real_schedule = _LoopWork.schedule

    def schedule_then_lose_the_loop(
        work: _LoopWork, coro: Coroutine[Any, Any, Any]
    ) -> concurrent.futures.Future[Any]:
        """Schedule, then unpublish as a dying loop would before the future is published."""
        fut = real_schedule(work, coro)
        host._lifecycle.state = _LoopState("dead")
        return fut

    monkeypatch.setattr(_LoopWork, "schedule", schedule_then_lose_the_loop)

    try:
        fut = host._schedule(asyncio.sleep, (1,), {})
    finally:
        monkeypatch.undo()
        host._lifecycle.state = real_state

    assert fut.cancelled()
    assert not host._pending
    host._stop(5)


def test_schedule_closes_its_coroutine_when_scheduling_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _running_host()
    seen: list[Coroutine[Any, Any, Any]] = []

    def refuse(_work: _LoopWork, coro: Coroutine[Any, Any, Any]) -> None:
        """Fail as a loop closing meanwhile would."""
        seen.append(coro)
        msg = "Event loop is closed"
        raise RuntimeError(msg)

    monkeypatch.setattr(_LoopWork, "schedule", refuse)

    with pytest.raises(RuntimeError, match="Event loop is closed"):
        host._schedule(asyncio.sleep, (0,), {})

    monkeypatch.undo()
    assert inspect.getcoroutinestate(seen[0]) == inspect.CORO_CLOSED
    assert not host._pending
    host._stop(5)


@pytest.mark.skipif(sys.version_info < (3, 12), reason="`loop_factory` arrived in 3.12")
def test_a_submission_landing_in_the_last_shutdown_pass_logs_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    in_shutdown = threading.Event()
    landed = threading.Event()

    def factory() -> asyncio.AbstractEventLoop:
        """Build a loop that holds its last shutdown pass until the submission landed."""
        loop = asyncio.new_event_loop()
        real_shutdown = loop.shutdown_default_executor

        async def shutdown_default_executor(timeout: float | None = None) -> None:
            """Let the held submission land, then shut down as usual."""
            in_shutdown.set()
            landed.wait(5)
            await real_shutdown(timeout)

        loop.shutdown_default_executor = shutdown_default_executor  # ty: ignore[invalid-assignment] - an instance override of the method, for this loop only
        return loop

    host = _running_host(loop_factory=factory)
    real_schedule = _LoopWork.schedule
    checked = threading.Event()

    def schedule_late(work: _LoopWork, coro: Coroutine[Any, Any, Any]) -> Any:
        """Pass `_checked_work` while running, then land only in the last shutdown pass."""
        checked.set()
        in_shutdown.wait(5)
        fut = real_schedule(work, coro)
        landed.set()
        return fut

    monkeypatch.setattr(_LoopWork, "schedule", schedule_late)
    outcome: list[concurrent.futures.Future[Any]] = []
    producer = threading.Thread(target=lambda: outcome.append(host._schedule(_noop, (), {})))

    with caplog.at_level(logging.ERROR):
        producer.start()
        assert checked.wait(5)  # Accepted while running, before the stop below.
        assert host._stop(5) is None
        producer.join(5)
        gc.collect()  # A task left pending would log "destroyed but it is pending" here.

    assert outcome[0].cancelled()  # Refused before any task was created.
    assert not [r for r in caplog.records if r.name in ("asyncio", "concurrent.futures")]


def _produce_while(
    host: _LoopHost, end: Callable[[], object]
) -> list[concurrent.futures.Future[Any]]:
    """Submit from 8 threads, 200 each, while `end` stops or kills the host; return the futures."""
    start = threading.Barrier(9)
    futures: list[concurrent.futures.Future[Any]] = []
    refused: list[RuntimeError] = []

    def produce() -> None:
        """Submit until the host refuses."""
        start.wait(5)

        for _ in range(200):
            try:
                futures.append(host._schedule(_noop, (), {}))
            except RuntimeError as e:
                refused.append(e)

    producers = [threading.Thread(target=produce, daemon=True) for _ in range(8)]

    for producer in producers:
        producer.start()

    start.wait(5)
    end()

    for producer in producers:
        producer.join(5)

    assert len(futures) + len(refused) == 8 * 200
    return futures


def test_schedule_from_many_threads_while_stopping_never_hangs() -> None:
    host = _running_host()
    futures = _produce_while(host, lambda: host._stop(10))

    for fut in futures:
        with contextlib.suppress(concurrent.futures.CancelledError):
            fut.result(5)  # Done or cancelled, never pending.

    assert not host._pending


def test_schedule_from_many_threads_while_the_loop_dies_never_hangs() -> None:
    host = _running_host()

    async def stop_loop() -> None:
        """Stop the loop from inside, which ends the thread."""
        asyncio.get_running_loop().stop()

    futures = _produce_while(host, lambda: host._schedule(stop_loop, (), {}))
    _host_thread(host).join(10)

    for fut in futures:
        with contextlib.suppress(concurrent.futures.CancelledError):
            fut.result(5)  # Done or cancelled, never pending.

    assert not host._pending
    assert isinstance(host._stop(5), RuntimeError)


def test_a_dying_loop_fails_every_pending_submission() -> None:
    host = _running_host()
    orphan: concurrent.futures.Future[Any] = concurrent.futures.Future()
    orphan_coro = _noop()
    host._pending[orphan] = orphan_coro  # As if its task was never created before the loop died.

    async def stop_loop() -> None:
        """Stop the loop from inside, which ends the thread."""
        asyncio.get_running_loop().stop()

    host._schedule(stop_loop, (), {})
    _host_thread(host).join(5)

    assert orphan.cancelled()
    assert inspect.getcoroutinestate(orphan_coro) == inspect.CORO_CLOSED  # Never warns unawaited.
    assert host._state().phase == "dead"
    assert isinstance(host._stop(5), RuntimeError)  # Asyncio's "stopped before Future completed".


def test_stop_on_a_never_started_host_abandons_it() -> None:
    host = _LoopHost(run_now=False)

    assert host._stop() is None
    assert host._state().phase == "abandoned"
    assert host.is_stopping()
    assert not host.is_started()

    with pytest.raises(RuntimeError, match="already been asked to stop"):
        host.run()


def test_stop_during_startup_never_publishes_and_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[bool] = []
    real_publish = loop_host._LoopLifecycle.publish

    def publish(self: Any, work: _LoopWork) -> bool:
        """Let the stop land first, then publish."""
        stopped.wait(5)
        seen.append(real_publish(self, work))
        return seen[-1]

    stopped = threading.Event()
    monkeypatch.setattr(loop_host._LoopLifecycle, "publish", publish)
    host = _LoopHost()
    results: list[BaseException | None] = []
    stopper = threading.Thread(target=lambda: results.append(host._stop(5)), daemon=True)
    stopper.start()

    while not host.is_stopping():
        threading.Event().wait(0.001)

    stopped.set()
    stopper.join(5)

    assert seen == [False]
    assert results == [None]
    assert host._state() == _LoopState("stopped")


def test_stop_after_a_startup_death_returns_the_death_every_time(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    boom = OSError("no loop")
    _fail_startup(monkeypatch, boom)
    host = _LoopHost()

    assert host._stop(5) is boom
    assert host._stop(5) is boom
    assert host.is_finished()
    assert not caplog.records  # Returned, never logged.


def test_concurrent_stops_return_the_same_outcome() -> None:
    host = _running_host()
    start = threading.Barrier(4)
    results: list[BaseException | None] = []

    def stop() -> None:
        """Stop together with the others."""
        start.wait(5)
        results.append(host._stop(5))

    stoppers = [threading.Thread(target=stop, daemon=True) for _ in range(4)]

    for stopper in stoppers:
        stopper.start()

    for stopper in stoppers:
        stopper.join(10)

    assert results == [None] * 4
    assert host._state() == _LoopState("stopped")


def test_stop_times_out_while_a_submission_runs() -> None:
    host = _running_host()
    fut = host._schedule(asyncio.sleep, (0.3,), {})

    with pytest.raises(TimeoutError, match="did not stop within 0.01"):
        host._stop(0.01)

    host._stop(5)
    assert fut.done()
    assert not fut.cancelled()  # Accepted before the stop: drained, not dropped.
    assert host.is_finished()


def test_run_waits_until_running_when_asked() -> None:
    worker = AioThreadWorker(run_now=False)
    worker.run(wait=5)

    assert worker.is_started()
    assert worker.is_running()
    worker.wait_for_running()  # Returns at once while running.
    asyncio.run(worker.join(timeout=5))


def test_run_with_a_short_wait_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _hold_startup(monkeypatch)
    host = _LoopHost(run_now=False)

    try:
        with pytest.raises(TimeoutError, match="did not start running within 0.05"):
            host.run(wait=0.05)
    finally:
        release.set()

    host._stop(5)


def test_run_refuses_a_second_call_even_while_alive() -> None:
    host = _running_host()

    with pytest.raises(RuntimeError, match="run\\(\\) starts it only once"):
        host.run()

    assert host.is_running()
    host._stop(5)


def test_ensure_started_tolerates_a_started_host() -> None:
    host = _running_host()
    thread = _host_thread(host)
    host._ensure_started()

    assert _host_thread(host) is thread
    host._stop(5)


def test_ensure_started_refuses_a_stopped_or_finished_host() -> None:
    abandoned = _LoopHost(run_now=False)
    abandoned._stop()

    with pytest.raises(RuntimeError, match="already been asked to stop"):
        abandoned._ensure_started()

    finished = _running_host()
    finished._stop(5)

    with pytest.raises(RuntimeError, match="finished and cannot be restarted"):
        finished._ensure_started()


def test_run_after_a_failed_thread_start_is_refused_for_good(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _LoopHost(run_now=False)
    _refuse_thread_start(monkeypatch)

    with pytest.raises(RuntimeError, match="can't start new thread") as caught:
        host.run()

    monkeypatch.undo()
    assert host._state().phase == "dead"
    assert host.is_finished()

    with pytest.raises(RuntimeError, match="finished and cannot be restarted"):
        host.run()

    assert host._stop(5) is caught.value


def test_run_refuses_a_stopped_or_finished_host() -> None:
    abandoned = _LoopHost(run_now=False)
    abandoned._stop()

    with pytest.raises(RuntimeError, match="already been asked to stop"):
        abandoned.run()

    finished = _running_host()
    finished._stop(5)

    with pytest.raises(RuntimeError, match="finished and cannot be restarted"):
        finished.run()


def test_loop_factory_builds_the_loop_where_python_allows_it() -> None:
    built: list[asyncio.AbstractEventLoop] = []

    def factory() -> asyncio.AbstractEventLoop:
        """Build and remember a loop."""
        loop = asyncio.new_event_loop()
        built.append(loop)
        return loop

    if sys.version_info < (3, 12):
        with pytest.warns(UserWarning, match="loop_factory is ignored"):
            host = _LoopHost(loop_factory=factory, run_now=False)
    else:
        host = _LoopHost(loop_factory=factory, run_now=False)

    host.run(wait=5)
    host._stop(5)
    assert len(built) == (0 if sys.version_info < (3, 12) else 1)


def test_thread_death_during_startup_is_reported_not_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    boom = OSError("no loop")
    _fail_startup(monkeypatch, boom)
    host = _LoopHost(name="dying")

    with pytest.raises(RuntimeError, match="its thread ended") as caught:
        host.wait_for_running(5)

    assert caught.value.__cause__ is boom
    assert host.is_finished()
    assert not caplog.records


def test_wait_for_running_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _hold_startup(monkeypatch)
    host = _LoopHost()

    try:
        with pytest.raises(TimeoutError, match="did not start running within 0.05"):
            host.wait_for_running(0.05)
    finally:
        release.set()

    _host_thread(host).join(5)
    assert host.is_finished()


def test_wait_for_running_refuses_a_host_never_started() -> None:
    with pytest.raises(RuntimeError, match="not been started"):
        _LoopHost(run_now=False).wait_for_running()
