from __future__ import annotations as _annotations

import threading
from typing import Any

import pytest

from pytrove.async_tools._internal import _LoopLifecycle, _LoopState

_WORK: Any = object()  # Stands in for a `_LoopWork`: the lifecycle never looks inside it.


def _started(main: Any = lambda: None, name: str | None = None) -> _LoopLifecycle:
    """Return a lifecycle whose thread already runs `main`."""
    lifecycle = _LoopLifecycle(name)
    lifecycle.start(main, again_ok=False)
    return lifecycle


def _thread(lifecycle: _LoopLifecycle) -> threading.Thread:
    """Return the lifecycle's started thread."""
    thread = lifecycle.thread
    assert thread is not None
    return thread


def test_lifecycle_starts_new() -> None:
    lifecycle = _LoopLifecycle("t")

    assert lifecycle.name == "t"
    assert lifecycle.state == _LoopState("new")
    assert lifecycle.thread is None
    assert not lifecycle.is_current()


def test_start_runs_one_named_daemon_thread_that_already_knows_itself() -> None:
    seen: list[tuple[bool, str]] = []
    lifecycle = _LoopLifecycle("named")

    def main() -> None:
        """Check, first thing, that the thread knows itself and is starting."""
        seen.append((lifecycle.is_current(), lifecycle.state.phase))

    lifecycle.start(main, again_ok=False)
    _thread(lifecycle).join(5)

    assert seen == [(True, "starting")]
    assert _thread(lifecycle).name == "named"
    assert _thread(lifecycle).daemon


def test_start_strict_refuses_a_second_start_even_while_alive() -> None:
    release = threading.Event()
    lifecycle = _started(lambda: release.wait(5))

    try:
        with pytest.raises(RuntimeError, match="starts it only once"):
            lifecycle.start(lambda: None, again_ok=False)
    finally:
        release.set()

    _thread(lifecycle).join(5)


def test_start_again_ok_tolerates_a_started_thread() -> None:
    release = threading.Event()
    lifecycle = _started(lambda: release.wait(5))
    thread = _thread(lifecycle)

    lifecycle.start(lambda: None, again_ok=True)
    release.set()

    assert lifecycle.thread is thread
    thread.join(5)


def test_concurrent_tolerant_starts_start_exactly_one_thread() -> None:
    gate = threading.Barrier(8)
    runs: list[int] = []
    lifecycle = _LoopLifecycle(None)

    def start() -> None:
        """Start together with the others."""
        gate.wait(5)
        lifecycle.start(lambda: runs.append(1), again_ok=True)

    starters = [threading.Thread(target=start, daemon=True) for _ in range(8)]

    for starter in starters:
        starter.start()

    for starter in starters:
        starter.join(5)

    _thread(lifecycle).join(5)
    assert runs == [1]


def test_a_failed_start_is_final_and_kept_as_the_death(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(_self: threading.Thread) -> None:
        """Fail as the OS refusing a new thread would."""
        msg = "can't start new thread"
        raise RuntimeError(msg)

    lifecycle = _LoopLifecycle(None)
    monkeypatch.setattr(threading.Thread, "start", refuse)

    with pytest.raises(RuntimeError, match="can't start new thread") as caught:
        lifecycle.start(lambda: None, again_ok=False)

    monkeypatch.undo()
    assert lifecycle.state == _LoopState("dead", death=caught.value)
    assert lifecycle.thread is None

    for again_ok in (False, True):
        with pytest.raises(RuntimeError, match="finished and cannot be restarted") as refused:
            lifecycle.start(lambda: None, again_ok=again_ok)

        assert refused.value.__cause__ is caught.value

    assert lifecycle.join(0) is caught.value


def test_publish_moves_starting_to_running_only() -> None:
    lifecycle = _LoopLifecycle(None)

    assert not lifecycle.publish(_WORK)  # Still new.

    lifecycle.state = _LoopState("starting")
    assert lifecycle.publish(_WORK)
    assert lifecycle.state == _LoopState("running", _WORK)
    assert not lifecycle.publish(_WORK)  # Already running.


def test_publish_after_a_stop_during_startup_returns_false() -> None:
    lifecycle = _LoopLifecycle(None)
    lifecycle.state = _LoopState("starting")

    assert lifecycle.request_stop() is None
    assert not lifecycle.publish(_WORK)
    assert lifecycle.state == _LoopState("stopping")


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("new", "abandoned"),
        ("starting", "stopping"),
        ("running", "stopping"),
        ("stopping", "stopping"),
        ("stopped", "stopped"),
        ("dead", "stopped"),
        ("abandoned", "abandoned"),
    ],
)
def test_request_stop_moves_each_phase_along_on_stop(before: Any, after: str) -> None:
    lifecycle = _LoopLifecycle(None)
    lifecycle.state = _LoopState(before)
    lifecycle.request_stop()

    assert lifecycle.state.phase == after


def test_request_stop_returns_the_work_to_every_call_while_it_is_up() -> None:
    lifecycle = _LoopLifecycle(None)
    lifecycle.state = _LoopState("running", _WORK)

    assert lifecycle.request_stop() is _WORK
    assert lifecycle.request_stop() is _WORK  # A drain request lost by the first is made again.
    assert lifecycle.state == _LoopState("stopping", _WORK)


def test_end_unpublishes_and_keeps_the_first_death() -> None:
    first = OSError("first")
    lifecycle = _LoopLifecycle(None)
    lifecycle.state = _LoopState("running", _WORK)

    lifecycle.end(first)
    assert lifecycle.state == _LoopState("dead", None, first)

    lifecycle.end(OSError("second"))
    assert lifecycle.state.death is first


def test_end_after_a_stop_finishes_as_stopped() -> None:
    lifecycle = _LoopLifecycle(None)
    lifecycle.state = _LoopState("stopping", _WORK)
    lifecycle.end(None)

    assert lifecycle.state == _LoopState("stopped")


def test_wait_for_running_wakes_on_publish() -> None:
    publish = threading.Event()
    lifecycle = _LoopLifecycle(None)

    def main() -> None:
        """Publish on request."""
        publish.wait(5)
        lifecycle.publish(_WORK)

    lifecycle.start(main, again_ok=False)
    threading.Timer(0.05, publish.set).start()
    lifecycle.wait_for_running(5)

    assert lifecycle.state.phase == "running"
    _thread(lifecycle).join(5)


def test_wait_for_running_raises_from_a_startup_death() -> None:
    boom = OSError("no loop")
    lifecycle = _LoopLifecycle(None)
    lifecycle.start(lambda: lifecycle.end(boom), again_ok=False)

    with pytest.raises(RuntimeError, match="its thread ended") as caught:
        lifecycle.wait_for_running(5)

    assert caught.value.__cause__ is boom


def test_wait_for_running_refuses_a_stop_during_startup() -> None:
    release = threading.Event()
    lifecycle = _started(lambda: release.wait(5))
    threading.Timer(0.05, lifecycle.request_stop).start()

    try:
        with pytest.raises(RuntimeError, match="worker is stopping"):
            lifecycle.wait_for_running(5)
    finally:
        release.set()

    _thread(lifecycle).join(5)


def test_wait_for_running_refuses_a_lifecycle_never_started() -> None:
    with pytest.raises(RuntimeError, match="not been started"):
        _LoopLifecycle(None).wait_for_running()


def test_wait_for_running_refuses_the_thread_itself() -> None:
    seen: list[BaseException] = []
    lifecycle = _LoopLifecycle(None)

    def main() -> None:
        """Wait for itself while still starting."""
        try:
            lifecycle.wait_for_running(1)
        except RuntimeError as e:
            seen.append(e)

    lifecycle.start(main, again_ok=False)
    _thread(lifecycle).join(5)

    assert len(seen) == 1
    assert "from inside the worker's own thread" in str(seen[0])


def test_wait_for_running_times_out() -> None:
    release = threading.Event()
    lifecycle = _started(lambda: release.wait(5))

    try:
        with pytest.raises(TimeoutError, match="did not start running within 0.05"):
            lifecycle.wait_for_running(0.05)
    finally:
        release.set()

    _thread(lifecycle).join(5)


def test_join_returns_the_death_every_time() -> None:
    boom = OSError("died")
    lifecycle = _LoopLifecycle(None)
    lifecycle.start(lambda: lifecycle.end(boom), again_ok=False)

    assert lifecycle.join(5) is boom
    assert lifecycle.join(5) is boom


def test_join_on_a_lifecycle_never_started_returns_none() -> None:
    assert _LoopLifecycle(None).join(0) is None


def test_join_times_out_then_succeeds() -> None:
    release = threading.Event()
    lifecycle = _started(lambda: release.wait(5))

    with pytest.raises(TimeoutError, match="did not stop within 0.01"):
        lifecycle.join(0.01)

    release.set()
    assert lifecycle.join(5) is None
