from __future__ import annotations as _annotations

import asyncio
from typing import Any

import pytest

from pytrove.async_tools import gather_abort, gather_helper


async def _value(v: Any, delay: float = 0) -> Any:
    """Return `v` after `delay` seconds."""
    await asyncio.sleep(delay)
    return v


async def _fail(exc: BaseException, delay: float = 0) -> None:
    """Raise `exc` after `delay` seconds."""
    await asyncio.sleep(delay)
    raise exc


async def test_gather_helper_collects_results_in_order() -> None:
    results = await gather_helper(_value(1), _value(2), _value(3))
    assert results == [1, 2, 3]


async def test_gather_helper_return_exc() -> None:
    results = await gather_helper(_value(1), _fail(ValueError("boom")), return_exc=True, log_exc=False)
    assert results[0] == 1
    assert isinstance(results[1], ValueError)


async def test_gather_helper_returns_a_cancelled_child_as_cancelled_error() -> None:
    async def hang() -> None:
        """Wait until cancelled."""
        await asyncio.Event().wait()

    child = asyncio.ensure_future(hang())
    asyncio.get_running_loop().call_soon(child.cancel)
    results = await gather_helper(child, return_exc=True, log_exc=False)
    assert isinstance(results[0], asyncio.CancelledError)


async def test_gather_helper_flattens_skips_none_and_logs_returned_failures(caplog: pytest.LogCaptureFixture) -> None:
    results = await gather_helper([_value(1), None, (_fail(KeyError()),)], return_exc=True)
    assert results[0] == 1
    assert isinstance(results[1], KeyError)
    assert "awaitable index=1" in caplog.text


async def test_gather_abort_cancels_siblings_on_error() -> None:
    cancelled = asyncio.Event()

    async def slow() -> None:
        """Record the cancellation, then let it through."""
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with pytest.raises(ValueError, match="boom"):
        await gather_abort(slow(), _fail(ValueError("boom")), log_exc=False)

    # `gather_abort`'s outer future resolves as soon as the first error is set; the cancelled
    # sibling's `except` block runs on a later loop iteration, so yield a few times first.
    for _ in range(10):
        await asyncio.sleep(0)

    assert cancelled.is_set()


async def test_gather_abort_cancels_the_rest_on_failure() -> None:
    slow = asyncio.ensure_future(_value(1, delay=5))

    with pytest.raises(KeyError):
        await gather_abort(slow, _fail(KeyError()))

    await asyncio.sleep(0)
    assert slow.cancelled()


async def test_gather_abort_returns_failures_when_asked(caplog: pytest.LogCaptureFixture) -> None:
    results = await gather_abort(_value(1), _fail(KeyError()), return_exc=True)
    assert results[0] == 1
    assert isinstance(results[1], KeyError)
    assert "error in gather_abort" in caplog.text


async def test_gather_helpers_take_an_explicit_false_return_exc() -> None:
    assert await gather_helper(_value(1), return_exc=False) == [1]
    assert await gather_abort([_value(1), _value(2)], return_exc=False) == [1, 2]
