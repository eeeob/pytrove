from __future__ import annotations as _annotations

import asyncio
import threading
from typing import Any

import pytest

from pytrove.async_tools import SyncAwaitableRunner

_LOOP_ATTR = "_SyncAwaitableRunner__loop"


async def _thread_id() -> int:
    """Return the id of the thread this runs on."""
    return threading.get_ident()


def test_runner_keeps_one_loop_across_calls() -> None:
    with SyncAwaitableRunner(name="r") as runner:
        first = runner.run(_thread_id())
        assert runner(_thread_id()) == first
        assert runner.running

    assert runner.closed
    assert not runner.running
    coro = _thread_id()

    with pytest.raises(RuntimeError, match="is not running"):
        runner.run(coro)

    coro.close()


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


def test_close_drains_tasks_left_on_the_loop() -> None:
    finished: list[int] = []

    async def background() -> None:
        """Finish a little after the call that spawned it."""
        await asyncio.sleep(0.02)
        finished.append(1)

    async def spawn() -> None:
        """Leave a task running on the loop."""
        asyncio.ensure_future(background())

    runner = SyncAwaitableRunner()
    runner.run(spawn())
    runner.close()

    assert finished == [1]


def test_start_refuses_a_closed_runner() -> None:
    runner = SyncAwaitableRunner(lazy=True)
    runner.close()

    with pytest.raises(RuntimeError, match="is closed"):
        runner.start()


def test_run_refuses_a_closed_runner_that_never_started() -> None:
    runner = SyncAwaitableRunner(lazy=True)
    runner.close()
    coro = asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="is closed"):
        runner.run(coro)

    coro.close()


def test_run_tolerates_losing_the_start_race(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = SyncAwaitableRunner(lazy=True)
    real_start = runner.start

    def start_then_lose() -> None:
        """Start, then fail as a concurrent `start` that came second would."""
        real_start()
        msg = "SyncAwaitableRunner is already started"
        raise RuntimeError(msg)

    monkeypatch.setattr(runner, "start", start_then_lose)
    assert runner.run(asyncio.sleep(0, result=4)) == 4
    runner.close()


def test_run_runs_any_awaitable_not_only_coroutines() -> None:
    class _Ready:
        """An awaitable that is not a coroutine."""

        def __await__(self) -> Any:
            """Resolve to 6 at once."""
            return asyncio.sleep(0, result=6).__await__()

    with SyncAwaitableRunner() as runner:
        assert runner.run(_Ready()) == 6


def test_run_reports_a_loop_that_disappears_while_scheduling() -> None:
    runner = SyncAwaitableRunner()
    real_loop = getattr(runner, _LOOP_ATTR)
    setattr(runner, _LOOP_ATTR, object())  # Has no `call_soon_threadsafe`.
    coro = asyncio.sleep(0)

    try:
        with pytest.raises(RuntimeError, match="disappeared while scheduling"):
            runner.run(coro)
    finally:
        setattr(runner, _LOOP_ATTR, real_loop)
        coro.close()

    runner.close()


def test_run_reports_a_loop_that_stopped_running() -> None:
    runner = SyncAwaitableRunner()
    real_loop = getattr(runner, _LOOP_ATTR)
    idle_loop = asyncio.new_event_loop()
    setattr(runner, _LOOP_ATTR, idle_loop)

    try:
        with pytest.raises(RuntimeError, match="no longer running"):
            runner.run(asyncio.sleep(0))
    finally:
        setattr(runner, _LOOP_ATTR, real_loop)
        idle_loop.run_until_complete(asyncio.sleep(0.01))  # Runs the scheduled coroutine, so it is not leaked.
        idle_loop.close()

    runner.close()


def test_close_refuses_the_runners_own_thread() -> None:
    with SyncAwaitableRunner() as runner:

        async def close_from_inside() -> None:
            """Close the runner from its own loop."""
            runner.close()

        with pytest.raises(RuntimeError, match="from inside the runner's own thread"):
            runner.run(close_from_inside())

    assert runner.closed
