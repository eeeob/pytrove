from __future__ import annotations as _annotations

import asyncio
from typing import Any

import pytest

from pytrove.async_tools import call_sync_or_await, run_awaitable_in_coro, to_thread, yield_control


async def _value(v: Any, delay: float = 0) -> Any:
    """Return `v` after `delay` seconds."""
    await asyncio.sleep(delay)
    return v


def _raise_value_error() -> None:
    """Fail."""
    msg = "x"
    raise ValueError(msg)


async def test_to_thread_runs_sync_func_in_executor() -> None:
    result = await to_thread(lambda x, y: x + y, 2, 3)
    assert result == 5


async def test_to_thread_return_exc() -> None:
    result = await to_thread(_raise_value_error, return_exc=True, log_exc=False)
    assert isinstance(result, ValueError)


async def test_to_thread_returns_or_raises_a_failure(caplog: pytest.LogCaptureFixture) -> None:
    assert isinstance(await to_thread(_raise_value_error, return_exc=True), ValueError)
    assert "error in to_thread" in caplog.text

    with pytest.raises(ValueError, match="x"):
        await to_thread(_raise_value_error, log_exc=False)


@pytest.mark.parametrize("return_exc", [False, True])
async def test_to_thread_takes_return_exc_as_a_plain_bool(return_exc: bool) -> None:
    assert await to_thread(int, "7", return_exc=return_exc, log_exc=False) == 7

    if return_exc:
        assert isinstance(
            await to_thread(_raise_value_error, return_exc=return_exc, log_exc=False), ValueError
        )
    else:
        with pytest.raises(ValueError, match="x"):
            await to_thread(_raise_value_error, return_exc=return_exc, log_exc=False)


async def test_call_sync_or_await_handles_both_kinds() -> None:
    assert await call_sync_or_await(lambda x: x + 1, 1) == 2
    assert await call_sync_or_await(_value, 3) == 3


async def test_run_awaitable_in_coro_wraps_any_awaitable() -> None:
    future = asyncio.get_running_loop().create_future()
    future.set_result(7)
    assert await run_awaitable_in_coro(future) == 7


async def test_yield_control_returns_none() -> None:
    assert await yield_control() is None


async def test_yield_control_interleaves_concurrent_tasks() -> None:
    order: list[str] = []

    async def worker(name: str) -> None:
        """Record three steps, yielding between them."""
        for i in range(3):
            order.append(f"{name}{i}")
            await yield_control()

    await asyncio.gather(worker("A"), worker("B"))

    assert order == ["A0", "B0", "A1", "B1", "A2", "B2"]
