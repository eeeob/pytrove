from __future__ import annotations as _annotations

import asyncio
import concurrent.futures
import inspect
import sys
import threading
from typing import Any, TYPE_CHECKING

import pytest

from pytrove.async_tools import SyncAwaitableRunner
from pytrove.async_tools._internal import loop_host

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

_HOST_ATTR = "_SyncAwaitableRunner__host"


async def _thread_id() -> int:
    """Return the id of the thread this runs on."""
    return threading.get_ident()


def _in_thread(func: Callable[[], Any], timeout: float = 5) -> list[Any]:
    """Run `func` in a daemon thread and fail, instead of hanging, if it blocks.

    Returns:
        A one-item list with the result or the exception raised.
    """
    outcome: list[Any] = []

    def call() -> None:
        """Keep the outcome of `func`."""
        try:
            outcome.append(func())
        except BaseException as e:  # noqa: BLE001 - the test inspects whatever it was
            outcome.append(e)

    thread = threading.Thread(target=call, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), "blocked instead of returning"
    return outcome


def _fail_startup(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    """Make the next loop thread die before its loop ever runs."""

    def run_loop(
        coro: Coroutine[Any, Any, Any], _factory: Callable[[], asyncio.AbstractEventLoop] | None
    ) -> None:
        """Fail before the loop ever runs."""
        coro.close()
        raise exc

    monkeypatch.setattr(loop_host, "_run_loop", run_loop)


def test_runner_keeps_one_loop_across_calls() -> None:
    with SyncAwaitableRunner(name="r") as runner:
        first = runner.run(_thread_id())
        assert runner(_thread_id()) == first
        assert runner.running
        thread = getattr(runner, _HOST_ATTR)._lifecycle.thread
        assert thread.name == "r"
        assert thread.daemon

    assert runner.closed
    assert runner.started  # Never goes back.
    assert not runner.running
    coro = _thread_id()

    with pytest.raises(RuntimeError, match="is closed"):
        runner.run(coro)

    assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED


def test_run_passes_on_what_the_awaitable_raises() -> None:
    async def boom() -> None:
        """Fail."""
        msg = "k"
        raise KeyError(msg)

    with SyncAwaitableRunner() as runner, pytest.raises(KeyError, match="k"):
        runner.run(boom())


def test_lazy_runner_starts_on_first_use() -> None:
    runner = SyncAwaitableRunner(lazy=True)
    assert not runner.started
    assert not runner.running
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


def test_close_lets_runs_finish_and_cancels_tasks_left_behind() -> None:
    events: list[str] = []
    background: list[asyncio.Task[None]] = []  # The loop holds tasks weakly: keep it from the GC.

    async def forever() -> None:
        """Run until cancelled, recording the cancellation."""
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            events.append("background cancelled")
            raise

    async def spawn() -> None:
        """Leave a task that never ends on the loop."""
        background.append(asyncio.ensure_future(forever()))

    runner = SyncAwaitableRunner()
    runner.run(spawn())
    _in_thread(lambda: runner.close(timeout=5))

    assert events == ["background cancelled"]


def test_close_waits_for_a_run_blocked_in_another_thread() -> None:
    runner = SyncAwaitableRunner()
    outcome: list[int] = []
    thread = threading.Thread(
        target=lambda: outcome.append(runner.run(asyncio.sleep(0.1, result=1)))
    )
    thread.start()
    threading.Event().wait(0.02)
    runner.close(timeout=5)
    thread.join(5)

    assert outcome == [1]


def test_runner_is_not_running_while_it_drains() -> None:
    runner = SyncAwaitableRunner()
    thread = threading.Thread(target=runner.run, args=(asyncio.sleep(0.1),))
    thread.start()
    threading.Event().wait(0.02)
    closing = threading.Thread(target=runner.close)
    closing.start()
    threading.Event().wait(0.02)

    assert runner.closed
    assert not runner.running
    closing.join(5)
    thread.join(5)


def test_close_times_out_while_a_run_is_still_going() -> None:
    runner = SyncAwaitableRunner()
    thread = threading.Thread(target=runner.run, args=(asyncio.sleep(0.3),))
    thread.start()
    threading.Event().wait(0.02)

    with pytest.raises(TimeoutError, match="did not close within 0.01"):
        runner.close(timeout=0.01)

    runner.close(timeout=5)
    thread.join(5)


def test_concurrent_runs_from_several_threads_share_the_loop() -> None:
    with SyncAwaitableRunner() as runner, concurrent.futures.ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: runner.run(_thread_id()), range(8)))

    assert len(set(results)) == 1


def test_start_refuses_a_closed_runner() -> None:
    runner = SyncAwaitableRunner(lazy=True)
    runner.close()

    with pytest.raises(RuntimeError, match="is closed"):
        runner.start()


def test_start_losing_a_start_race_says_already_started(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = SyncAwaitableRunner(lazy=True)
    host = getattr(runner, _HOST_ATTR)
    real_run = host.run

    def lose_the_race() -> None:
        """Let another thread's start win just before this one."""
        host._ensure_started()
        real_run()

    monkeypatch.setattr(host, "run", lose_the_race)

    with pytest.raises(RuntimeError, match="is already started$"):
        runner.start()

    runner.close(timeout=5)


def test_run_losing_a_race_with_close_says_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = SyncAwaitableRunner()
    host = getattr(runner, _HOST_ATTR)
    real_schedule = host._schedule

    def close_first(*args: Any) -> Any:
        """Let a `close` win just after the runner's own check."""
        host._stop(5)
        return real_schedule(*args)

    monkeypatch.setattr(host, "_schedule", close_first)
    coro = asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="is closed$"):
        runner.run(coro)

    assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED


def test_a_runner_whose_thread_never_started_reports_why(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = SyncAwaitableRunner(lazy=True)

    def refuse(_self: threading.Thread) -> None:
        """Refuse, as the OS refusing a new thread would."""
        msg = "can't start new thread"
        raise RuntimeError(msg)

    monkeypatch.setattr(threading.Thread, "start", refuse)

    with pytest.raises(RuntimeError, match="failed to start"):
        runner.run(asyncio.sleep(0))

    monkeypatch.undo()
    coro = asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="is not running") as not_running:
        runner.run(coro)

    with pytest.raises(RuntimeError, match="event loop has ended") as ended:
        runner.start()

    assert str(not_running.value.__cause__) == "can't start new thread"
    assert ended.value.__cause__ is not_running.value.__cause__
    assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED


def test_run_refuses_a_closed_runner_that_never_started() -> None:
    runner = SyncAwaitableRunner(lazy=True)
    runner.close()
    coro = asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="is closed"):
        runner.run(coro)

    assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED


def test_concurrent_lazy_runs_start_one_loop() -> None:
    runner = SyncAwaitableRunner(lazy=True)
    gate = threading.Barrier(8)
    seen: list[int] = []

    def run() -> None:
        """Run together with the others, the first use of the runner."""
        gate.wait(5)
        seen.append(runner.run(_thread_id()))

    runners = [threading.Thread(target=run, daemon=True) for _ in range(8)]

    for thread in runners:
        thread.start()

    for thread in runners:
        thread.join(5)

    assert len(seen) == 8
    assert len(set(seen)) == 1
    runner.close(timeout=5)


def test_run_waits_for_a_start_in_progress_in_another_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_publish = loop_host._LoopLifecycle.publish
    release = threading.Event()

    def publish(self: Any, work: Any) -> bool:
        """Hold the loop in startup until released."""
        release.wait(5)
        return real_publish(self, work)

    monkeypatch.setattr(loop_host._LoopLifecycle, "publish", publish)
    runner = SyncAwaitableRunner(lazy=True)
    getattr(runner, _HOST_ATTR)._ensure_started()  # Another thread's start, still under way.
    threading.Timer(0.05, release.set).start()

    assert runner.run(asyncio.sleep(0, result=4)) == 4
    runner.close(timeout=5)


def test_run_runs_any_awaitable_not_only_coroutines() -> None:
    class _Ready:
        """An awaitable that is not a coroutine."""

        def __await__(self) -> Any:
            """Resolve to 6 at once."""
            return asyncio.sleep(0, result=6).__await__()

    with SyncAwaitableRunner() as runner:
        assert runner.run(_Ready()) == 6


def test_run_refuses_the_runners_own_thread() -> None:
    runner = SyncAwaitableRunner()

    async def nested() -> int:
        """Run on the runner from its own loop."""
        return runner.run(asyncio.sleep(0, result=1))

    outcome = _in_thread(lambda: runner.run(nested()))
    runner.close(timeout=5)

    assert isinstance(outcome[0], RuntimeError)
    assert "from inside the runner's own thread" in str(outcome[0])


def test_close_refuses_the_runners_own_thread() -> None:
    with SyncAwaitableRunner() as runner:

        async def close_from_inside() -> None:
            """Close the runner from its own loop."""
            runner.close()

        with pytest.raises(RuntimeError, match="from inside the runner's own thread"):
            runner.run(close_from_inside())

    assert runner.closed


def test_an_interrupted_run_cancels_its_awaitable(monkeypatch: pytest.MonkeyPatch) -> None:
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

    def interrupted(_fut: concurrent.futures.Future[Any], _timeout: float | None = None) -> Any:
        """Stand in for a wait that `KeyboardInterrupt` breaks once the work runs."""
        started.wait(5)
        raise KeyboardInterrupt

    runner = SyncAwaitableRunner()
    monkeypatch.setattr(concurrent.futures.Future, "result", interrupted)

    with pytest.raises(KeyboardInterrupt):
        runner.run(hang())

    monkeypatch.undo()
    assert cancelled.wait(5)
    runner.close(timeout=5)


def test_a_run_lost_with_a_dying_loop_fails_instead_of_hanging() -> None:
    async def stop_loop() -> None:
        """Stop the runner's loop from inside, which ends its thread."""
        asyncio.get_running_loop().stop()

    runner = SyncAwaitableRunner()
    hung = concurrent.futures.ThreadPoolExecutor(1)
    pending = hung.submit(runner.run, asyncio.sleep(10))
    threading.Event().wait(0.02)
    runner.run(stop_loop())

    # The teardown cancels it while the flags may still read "running", so either error is
    # possible; what matters is that it fails instead of hanging.
    with pytest.raises((RuntimeError, concurrent.futures.CancelledError)):
        pending.result(5)

    hung.shutdown()
    assert isinstance(runner.close(timeout=5), RuntimeError)  # The loop's death, returned.


def test_exiting_closes_without_suppressing_the_error() -> None:
    with pytest.raises(KeyError), SyncAwaitableRunner() as runner:
        raise KeyError

    assert runner.closed
    assert not runner.running


def test_a_loop_that_fails_to_start_is_reported_with_its_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boom = OSError("no loop")
    _fail_startup(monkeypatch, boom)

    with pytest.raises(RuntimeError, match="event loop failed to start") as caught:
        SyncAwaitableRunner(lazy=False)

    assert caught.value.__cause__ is not None
    assert caught.value.__cause__.__cause__ is boom


def test_run_reports_a_loop_that_fails_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    _fail_startup(monkeypatch, OSError("no loop"))
    runner = SyncAwaitableRunner(lazy=True)
    coro = asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="event loop failed to start"):
        runner.run(coro)

    assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED
    death = runner.close(timeout=5)  # A failed runner still closes quietly...

    assert isinstance(death, OSError)  # ...and hands back why, every time.
    assert runner.close(timeout=5) is death
    assert runner.closed


def test_close_on_a_never_started_runner_returns_none() -> None:
    assert SyncAwaitableRunner(lazy=True).close() is None


def test_exiting_never_raises_the_death(monkeypatch: pytest.MonkeyPatch) -> None:
    _fail_startup(monkeypatch, OSError("no loop"))

    with SyncAwaitableRunner(lazy=True) as runner:
        pass

    assert runner.closed


def test_loop_factory_must_be_callable() -> None:
    with pytest.raises(TypeError, match="loop_factory"):
        SyncAwaitableRunner(lazy=True, loop_factory=5)


@pytest.mark.skipif(sys.version_info >= (3, 12), reason="the factory is honoured from 3.12 on")
def test_loop_factory_is_ignored_with_a_warning_before_312() -> None:
    with pytest.warns(UserWarning, match="loop_factory is ignored") as caught:
        runner = SyncAwaitableRunner(lazy=True, loop_factory=asyncio.new_event_loop)

    assert len(caught) == 1
    assert caught[0].filename == __file__
    runner.close()


@pytest.mark.skipif(sys.version_info < (3, 12), reason="the factory is ignored before 3.12")
def test_loop_factory_builds_the_loop_from_312() -> None:
    built: list[asyncio.AbstractEventLoop] = []

    def factory() -> asyncio.AbstractEventLoop:
        """Build and remember a loop."""
        loop = asyncio.new_event_loop()
        built.append(loop)
        return loop

    async def running_loop() -> asyncio.AbstractEventLoop:
        """Return the loop this runs on."""
        return asyncio.get_running_loop()

    with SyncAwaitableRunner(loop_factory=factory) as runner:
        assert [runner.run(running_loop())] == built


def test_loop_factory_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def factory() -> asyncio.AbstractEventLoop:
        """Fail to build a loop."""
        msg = "no loop"
        raise OSError(msg)

    if sys.version_info < (3, 12):  # The factory is ignored there: fail the loop driver instead.
        _fail_startup(monkeypatch, OSError("no loop"))

        with pytest.warns(UserWarning), pytest.raises(RuntimeError, match="failed to start"):
            SyncAwaitableRunner(loop_factory=factory)
    else:
        with pytest.raises(RuntimeError, match="failed to start"):
            SyncAwaitableRunner(loop_factory=factory)
