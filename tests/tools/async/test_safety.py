from __future__ import annotations as _annotations

import asyncio
from typing import Any

import pytest

from pytrove.async_tools import safe_await


async def _value(v: Any, delay: float = 0) -> Any:
    """Return `v` after `delay` seconds."""
    await asyncio.sleep(delay)
    return v


async def _fail(exc: BaseException, delay: float = 0) -> None:
    """Raise `exc` after `delay` seconds."""
    await asyncio.sleep(delay)
    raise exc


async def test_safe_await_logs_a_single_failure_without_an_index(caplog: pytest.LogCaptureFixture) -> None:
    assert isinstance(await safe_await(_fail(KeyError("one"))), KeyError)
    assert "error in safe_await\n" in caplog.text
    assert "awaitable index" not in caplog.text


async def test_safe_await_logs_each_failure_of_several_with_its_index(caplog: pytest.LogCaptureFixture) -> None:
    results = await safe_await(_value(1), _fail(KeyError("two")))

    assert results[0] == 1
    assert isinstance(results[1], KeyError)
    assert "error in safe_await [awaitable index=1]" in caplog.text


async def test_safe_await_of_nothing_is_an_empty_list() -> None:
    assert await safe_await() == []
