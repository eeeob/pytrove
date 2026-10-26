from __future__ import annotations as _annotations

import asyncio
import inspect
import sys
import warnings
import pytest

from pytrove.async_tools import AioThreadWorker
from pytrove.async_tools._internal import (
    _close_if_unstarted,
    _check_loop_factory,
    _run_loop,
)


async def _noop() -> None:
    """Do nothing."""


def test_close_if_unstarted_closes_only_a_fresh_coroutine() -> None:
    fresh = _noop()
    _close_if_unstarted(fresh)
    assert inspect.getcoroutinestate(fresh) == inspect.CORO_CLOSED

    async def suspended() -> None:
        """Suspend once."""
        await asyncio.sleep(0)

    started = suspended()
    started.send(None)
    _close_if_unstarted(started)
    assert inspect.getcoroutinestate(started) == inspect.CORO_SUSPENDED
    started.close()

    _close_if_unstarted(asyncio.sleep)  # Not a coroutine: left alone.


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


@pytest.mark.skipif(sys.version_info >= (3, 12), reason="the factory is honoured from 3.12 on")
def test_check_loop_factory_warns_at_the_users_constructor_call() -> None:
    with pytest.warns(UserWarning, match="loop_factory is ignored") as caught:
        AioThreadWorker(loop_factory=asyncio.new_event_loop, run_now=False)

    assert caught[0].filename == __file__


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


@pytest.mark.skipif(sys.version_info < (3, 12), reason="the factory is ignored before 3.12")
def test_run_loop_closes_the_coroutine_when_the_factory_raises() -> None:
    def factory() -> asyncio.AbstractEventLoop:
        """Fail to build a loop."""
        msg = "no loop"
        raise OSError(msg)

    coro = _noop()

    with pytest.raises(OSError, match="no loop"):
        _run_loop(coro, factory)

    assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED
