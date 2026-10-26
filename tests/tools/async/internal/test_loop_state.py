from __future__ import annotations as _annotations

import asyncio
import re
from typing import Any, get_args

import pytest

from pytrove.async_tools._internal import _ON_END, _ON_STOP, _LoopState, _LoopWork, _Phase
from pytrove.async_tools._internal.loop_state import _REFUSALS, _START_REFUSALS

_PHASES: tuple[_Phase, ...] = get_args(_Phase)
_WORK: Any = object()  # Stands in for a `_LoopWork`: the snapshot never looks inside it.


def _state(phase: _Phase) -> _LoopState:
    """Return a snapshot in `phase`, with a loop where that phase has one."""
    return _LoopState(phase, _WORK if phase in ("running", "stopping") else None)


def test_phases_are_the_seven_of_the_lifecycle() -> None:
    assert _PHASES == ("new", "starting", "running", "stopping", "stopped", "dead", "abandoned")


def test_loop_state_defaults_to_no_work_and_no_death() -> None:
    state = _LoopState("new")

    assert state.work is None
    assert state.death is None


@pytest.mark.parametrize(
    ("phase", "started", "running", "accepting", "stopping", "finished", "gone", "needs_start"),
    [
        ("new", False, False, False, False, False, True, True),
        ("starting", True, False, False, False, False, True, True),
        ("running", True, True, True, False, False, False, False),
        ("stopping", True, True, False, True, False, True, False),
        ("stopped", True, False, False, True, True, True, False),
        ("dead", True, False, False, False, True, True, False),
        ("abandoned", False, False, False, True, False, True, False),
    ],
)
def test_queries_answer_from_the_phase(
    phase: _Phase,
    started: bool,
    running: bool,
    accepting: bool,
    stopping: bool,
    finished: bool,
    gone: bool,
    needs_start: bool,
) -> None:
    state = _state(phase)

    assert state.started is started
    assert state.running is running
    assert state.accepting is accepting
    assert state.stopping is stopping
    assert state.finished is finished
    assert state.gone is gone
    assert state.needs_start is needs_start


def test_running_follows_the_published_work_not_the_phase() -> None:
    assert not _LoopState("stopping").running  # Stopped while starting: no loop to drain.
    assert _LoopState("stopping", _WORK).running


def test_start_refusal_allows_only_new_when_strict() -> None:
    assert _state("new").start_refusal(again_ok=False) is None

    for phase in _PHASES[1:]:
        assert _state(phase).start_refusal(again_ok=False) == _START_REFUSALS[phase]


def test_start_refusal_tolerates_starting_and_running_when_again_ok() -> None:
    for phase in ("new", "starting", "running"):
        assert _state(phase).start_refusal(again_ok=True) is None

    for phase in ("stopping", "stopped", "dead", "abandoned"):
        assert _state(phase).start_refusal(again_ok=True) == _START_REFUSALS[phase]


@pytest.mark.parametrize(
    ("phase", "words"),
    [
        ("starting", "starts it only once"),
        ("running", "starts it only once"),
        ("stopping", "is stopping"),
        ("stopped", "finished"),
        ("dead", "finished"),
        ("abandoned", "already been asked to stop"),
    ],
)
def test_start_refusals_name_each_phase(phase: _Phase, words: str) -> None:
    assert words in _START_REFUSALS[phase]


@pytest.mark.parametrize("phase", ["new", "starting", "stopped", "dead", "abandoned"])
def test_checked_work_refuses_each_phase_without_a_loop(phase: _Phase) -> None:
    with pytest.raises(RuntimeError, match=re.escape(_REFUSALS[phase])):
        _state(phase).checked_work(new_work=False)


def test_checked_work_hands_out_a_draining_loop_but_refuses_new_work_on_it() -> None:
    state = _state("stopping")

    assert state.checked_work(new_work=False) is _WORK

    with pytest.raises(RuntimeError, match="worker is stopping"):
        state.checked_work(new_work=True)


def test_checked_work_returns_a_running_loop() -> None:
    assert _state("running").checked_work(new_work=True) is _WORK


def test_checked_work_chains_the_death() -> None:
    boom = OSError("no loop")

    with pytest.raises(RuntimeError, match="its thread ended") as caught:
        _LoopState("dead", death=boom).checked_work(new_work=False)

    assert caught.value.__cause__ is boom


def test_refusals_cover_every_phase_without_a_loop() -> None:
    assert set(_REFUSALS) == set(_PHASES) - {"running"}  # A running phase always has its loop.
    assert set(_START_REFUSALS) == set(_PHASES) - {"new"}


def test_on_stop_is_total_idempotent_and_never_leaves_the_stop_side() -> None:
    assert set(_ON_STOP) == set(_PHASES)

    for phase in _PHASES:
        after = _ON_STOP[phase]
        assert _ON_STOP[after] == after
        assert _LoopState(after).stopping


def test_on_end_is_total_and_finishes_every_phase_a_thread_runs_in() -> None:
    assert set(_ON_END) == set(_PHASES)

    for phase in ("starting", "running", "stopping", "stopped", "dead"):
        assert _LoopState(_ON_END[phase]).finished

    assert _ON_END["stopping"] == "stopped"
    assert _ON_END["running"] == "dead"


async def test_a_real_loop_work_rides_in_the_snapshot() -> None:
    work = _LoopWork(asyncio.get_running_loop(), 0)

    assert _LoopState("running", work).checked_work(new_work=True) is work
