import asyncio

import pytest

from pytrove import to_thread, gather_helper, gather_abort, safe_await



async def _ok(x):
    return x


async def _boom():
    raise ValueError("boom")


async def test_to_thread_runs_sync_func_in_executor():
    result = await to_thread(lambda x, y: x + y, 2, 3)
    assert result == 5


async def test_to_thread_return_exc():
    result = await to_thread(lambda: (_ for _ in ()).throw(ValueError("x")), return_exc=True, log_exc=False)
    assert isinstance(result, ValueError)


async def test_gather_helper_collects_results_in_order():
    results = await gather_helper(_ok(1), _ok(2), _ok(3))
    assert results == [1, 2, 3]


async def test_gather_helper_return_exc():
    results = await gather_helper(_ok(1), _boom(), return_exc=True, log_exc=False)
    assert results[0] == 1
    assert isinstance(results[1], ValueError)


async def test_gather_abort_cancels_siblings_on_error():
    cancelled = asyncio.Event()

    async def _slow():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError as e:
            cancelled.set()
            raise e

    with pytest.raises(ValueError):
        await gather_abort(_slow(), _boom(), log_exc=False)

    # gather_abort's outer future resolves as soon as the first error is set;
    # the cancelled sibling's except-block runs on a later loop iteration, so
    # yield control a few times before asserting it actually ran.
    for _ in range(10):
        await asyncio.sleep(0)

    assert cancelled.is_set()


async def test_safe_await_single_returns_exception_by_default():
    result = await safe_await(_boom(), log_exc=False)
    assert isinstance(result, ValueError)


async def test_safe_await_raises_when_return_exc_false():
    with pytest.raises(ValueError):
        await safe_await(_boom(), return_exc=False, log_exc=False)
