from __future__ import annotations as _annotations

import asyncio
import sys
import warnings

import pytest

from pytrove.async_tools._internal import _check_loop_factory, _run_loop, _run_tracked


def test_check_loop_factory() -> None:
    with pytest.raises(TypeError, match="loop_factory"):
        _check_loop_factory(5)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _check_loop_factory(asyncio.new_event_loop)

    assert bool(caught) is (sys.version_info < (3, 12))


def test_check_loop_factory_accepts_none_silently() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _check_loop_factory(None)


def test_run_loop_drives_a_coroutine() -> None:
    seen: list[int] = []

    async def mark() -> None:
        """Record that it ran."""
        seen.append(1)

    _run_loop(mark(), None)
    assert seen == [1]


def test_run_loop_uses_the_factory_where_python_allows_it() -> None:
    built: list[asyncio.AbstractEventLoop] = []
    used: list[asyncio.AbstractEventLoop] = []

    def factory() -> asyncio.AbstractEventLoop:
        """Build and remember a loop."""
        loop = asyncio.new_event_loop()
        built.append(loop)
        return loop

    async def record_loop() -> None:
        """Remember the loop this runs on."""
        used.append(asyncio.get_running_loop())

    _run_loop(record_loop(), factory)

    if sys.version_info < (3, 12):
        assert built == []
    else:
        assert built == used


async def test_run_tracked_registers_and_bounds_the_task() -> None:
    tasks: set[asyncio.Task[object]] = set()
    slots = asyncio.Semaphore(1)

    async def probe() -> int:
        """Report how many tasks are tracked while it runs."""
        return len(tasks)

    assert await _run_tracked(probe, (), {}, tasks, slots) == 1
    assert not tasks
    assert await _run_tracked(probe, (), {}, None, None) == 0

    with pytest.raises(TypeError, match="awaitable"):
        await _run_tracked(lambda: None, (), {}, tasks, None)


async def test_run_tracked_releases_the_slot_even_when_cancelled() -> None:
    slots = asyncio.Semaphore(1)
    tasks: set[asyncio.Task[object]] = set()

    async def hang() -> None:
        """Wait until cancelled."""
        await asyncio.Event().wait()

    task = asyncio.ensure_future(_run_tracked(hang, (), {}, tasks, slots))
    await asyncio.sleep(0)
    assert slots.locked()
    assert task in tasks

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert not slots.locked()
    assert not tasks
