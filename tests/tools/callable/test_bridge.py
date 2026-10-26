from __future__ import annotations as _annotations

import asyncio
import concurrent.futures
import contextlib
import inspect
import threading
from typing import TYPE_CHECKING, Any

import pytest

from pytrove.callable_tools import await_sync, run_awaitable_sync, to_coroutine

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator


async def test_to_coroutine_wraps_sync_function() -> None:
    coro_func = to_coroutine(lambda x, y: x + y)
    result = await coro_func(2, 3)
    assert result == 5


async def test_await_sync_calls_on_the_loop_thread() -> None:
    assert await await_sync(threading.get_ident) == threading.get_ident()


def test_run_awaitable_sync_creates_a_loop_when_none_is_given() -> None:
    async def seven() -> int:
        """Return seven."""
        return 7

    assert run_awaitable_sync(seven()) == 7


def test_run_awaitable_sync_uses_a_loop_running_in_another_thread() -> None:
    async def nine() -> int:
        """Return nine."""
        return 9

    with _loop_in_a_thread() as loop:
        assert run_awaitable_sync(nine(), loop) == 9


async def test_run_awaitable_sync_targets_another_thread_loop_from_inside_a_running_loop() -> None:
    async def ten() -> int:
        """Return ten."""
        return 10

    with _loop_in_a_thread() as loop:
        assert run_awaitable_sync(ten(), loop) == 10


def test_run_awaitable_sync_rejects_an_idle_or_closed_loop() -> None:
    loop = asyncio.new_event_loop()

    async def nothing() -> None:
        """Do nothing."""

    coro = nothing()
    with pytest.raises(RuntimeError, match="not running"):
        run_awaitable_sync(coro, loop)
    loop.close()

    with pytest.raises(RuntimeError, match="closed"):
        run_awaitable_sync(coro, loop)
    coro.close()


async def test_run_awaitable_sync_refuses_inside_a_running_loop() -> None:
    async def nothing() -> None:
        """Do nothing."""

    coro = nothing()
    with pytest.raises(RuntimeError, match="already running"):
        run_awaitable_sync(coro)
    assert coro.cr_frame is None

    with pytest.raises(RuntimeError, match="deadlock"):
        run_awaitable_sync(coro, asyncio.get_running_loop())
    coro.close()


class _Eight:
    """An awaitable that is not a coroutine."""

    def __await__(self) -> Generator[Any, None, int]:
        """Yield once to the loop, then give eight."""
        return (yield from asyncio.sleep(0, result=8).__await__())


async def _fail() -> None:
    """Raise `KeyError`."""
    raise KeyError


@contextlib.contextmanager
def _loop_in_a_thread() -> Iterator[asyncio.AbstractEventLoop]:
    """Run a fresh loop in a daemon thread for the duration of the block, already running."""
    loop = asyncio.new_event_loop()
    running = threading.Event()
    # The first callback runs once `run_forever` has started, so `is_running()` is true by then.
    loop.call_soon(running.set)
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    running.wait()

    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join()
        loop.close()


def test_run_awaitable_sync_runs_a_non_coroutine_awaitable() -> None:
    assert run_awaitable_sync(_Eight()) == 8

    with _loop_in_a_thread() as loop:
        assert run_awaitable_sync(_Eight(), loop) == 8


def test_run_awaitable_sync_propagates_the_awaitables_exception() -> None:
    with pytest.raises(KeyError):
        run_awaitable_sync(_fail())

    with _loop_in_a_thread() as loop, pytest.raises(KeyError):
        run_awaitable_sync(_fail(), loop)


def test_run_awaitable_sync_times_out_and_cancels() -> None:
    cancelled: list[bool] = []

    async def slow() -> None:
        """Sleep until cancelled, and record the cancellation."""
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        run_awaitable_sync(slow(), timeout=0.01)

    assert cancelled == [True]

    with _loop_in_a_thread() as loop:
        with pytest.raises((concurrent.futures.TimeoutError, TimeoutError)):
            run_awaitable_sync(slow(), loop, timeout=0.01)

        # The cancellation runs on the other thread's loop; wait for it there.
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0.05), loop).result()

    assert cancelled == [True, True]
    assert run_awaitable_sync(asyncio.sleep(0, result=3), timeout=1) == 3


def test_run_awaitable_sync_closes_a_refused_coroutine() -> None:
    loop = asyncio.new_event_loop()
    coro = _fail()

    with pytest.raises(RuntimeError, match="not running"):
        run_awaitable_sync(coro, loop)

    loop.close()
    assert coro.cr_frame is None


async def test_await_sync_and_to_coroutine_pass_keywords_and_errors() -> None:
    def combine(a: int, *, b: int) -> int:
        """Add `a` and `b`, refusing a negative `b`."""
        if b < 0:
            raise ValueError(b)
        return a + b

    assert await await_sync(combine, 1, b=2) == 3
    assert await to_coroutine(combine)(1, b=2) == 3

    with pytest.raises(ValueError):
        await await_sync(combine, 1, b=-1)

    with pytest.raises(ValueError):
        await to_coroutine(combine)(1, b=-1)


def test_to_coroutine_keeps_the_function_identity() -> None:
    def named() -> int:
        """Return one."""
        return 1

    coro_func = to_coroutine(named)
    assert coro_func.__name__ == "named"
    assert coro_func.__wrapped__ is named
    assert inspect.iscoroutinefunction(coro_func)
