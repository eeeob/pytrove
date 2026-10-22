from __future__ import annotations as _annotations

import asyncio
import threading
from typing import Any

import pytest

from pytrove.callable_tools import await_sync, run_awaitable_sync, to_coroutine


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

    future_holder: list[Any] = []

    async def wrap() -> int:
        """Await a non-coroutine awaitable."""
        future = asyncio.get_running_loop().create_future()
        future.set_result(8)
        future_holder.append(future)
        return await future

    assert run_awaitable_sync(wrap()) == 8


def test_run_awaitable_sync_uses_a_loop_running_in_another_thread() -> None:
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    try:

        async def nine() -> int:
            """Return nine."""
            return 9

        assert run_awaitable_sync(nine(), loop) == 9
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join()
        loop.close()


async def test_run_awaitable_sync_targets_another_thread_loop_from_inside_a_running_loop() -> None:
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    try:

        async def ten() -> int:
            """Return ten."""
            return 10

        assert run_awaitable_sync(ten(), loop) == 10
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join()
        loop.close()


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

    with pytest.raises(RuntimeError, match="deadlock"):
        run_awaitable_sync(coro, asyncio.get_running_loop())
    coro.close()
