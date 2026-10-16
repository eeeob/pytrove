from __future__ import annotations as _annotations

import asyncio
import functools
import sys
import traceback
from typing import Any

import pytest

from pytrove.async_tools import (
    asafe_call,
    call_sync_or_await,
    cancel_task,
    gather_abort,
    gather_helper,
    maybe_awaitable,
    run_awaitable_in_coro,
    safe_await,
    safe_wait_task,
    to_thread,
)
from pytrove.async_tools._internal import (
    _GatheringFuture,
    _gather_cancel_on_error,
    _get_fut_loop,
    _log_exc,
    _ExcLogger,
    _PY314,
)


async def _value(v: Any, delay: float = 0) -> Any:
    """Return `v` after `delay` seconds."""
    await asyncio.sleep(delay)
    return v


async def _fail(exc: BaseException, delay: float = 0) -> None:
    """Raise `exc` after `delay` seconds."""
    await asyncio.sleep(delay)
    raise exc


def test_py314_flag_matches_the_interpreter() -> None:
    assert _PY314 is (sys.version_info >= (3, 14))


def test_exc_logger_alias_exists() -> None:
    assert _ExcLogger is not None


async def test_call_sync_or_await_handles_both_kinds() -> None:
    assert await call_sync_or_await(lambda x: x + 1, 1) == 2
    assert await call_sync_or_await(_value, 3) == 3


async def test_run_awaitable_in_coro_wraps_any_awaitable() -> None:
    future = asyncio.get_running_loop().create_future()
    future.set_result(7)
    assert await run_awaitable_in_coro(future) == 7


async def test_to_thread_returns_or_raises_a_failure(caplog: pytest.LogCaptureFixture) -> None:
    def boom() -> None:
        """Fail."""
        raise ValueError

    assert isinstance(await to_thread(boom, return_exc=True), ValueError)
    assert "error in to_thread" in caplog.text

    with pytest.raises(ValueError):
        await to_thread(boom, log_exc=False)


@pytest.mark.parametrize("return_exc", [False, True])
async def test_to_thread_takes_return_exc_as_a_plain_bool(return_exc: bool) -> None:
    def boom() -> None:
        """Fail."""
        raise ValueError

    assert await to_thread(int, "7", return_exc=return_exc, log_exc=False) == 7

    if return_exc:
        assert isinstance(await to_thread(boom, return_exc=return_exc, log_exc=False), ValueError)
    else:
        with pytest.raises(ValueError):
            await to_thread(boom, return_exc=return_exc, log_exc=False)


@pytest.mark.parametrize("return_exc", [False, True])
async def test_maybe_awaitable_forwards_return_exc_to_every_path(return_exc: bool) -> None:
    def boom(_x: int, *, key: str) -> None:
        """Fail."""
        raise ValueError(key)

    async def aboom(_x: int, *, key: str) -> None:
        """Fail asynchronously."""
        raise ValueError(key)

    for awaitable_or_callable, args in ((_fail(ValueError("a")), ()), (aboom, (1,)), (boom, (1,))):
        kwargs = {"key": "k"} if args else {}

        if return_exc:
            result = await maybe_awaitable(awaitable_or_callable, *args, return_exc=True, log_exc=False, **kwargs)
            assert isinstance(result, ValueError)
        else:
            with pytest.raises(ValueError):
                await maybe_awaitable(awaitable_or_callable, *args, log_exc=False, **kwargs)


async def test_gather_helper_flattens_skips_none_and_logs_returned_failures(caplog: pytest.LogCaptureFixture) -> None:
    results = await gather_helper([_value(1), None, (_fail(KeyError()),)], return_exc=True)
    assert results[0] == 1
    assert isinstance(results[1], KeyError)
    assert "awaitable index=1" in caplog.text


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


async def test_safe_await_unwraps_a_single_awaitable_and_lists_several() -> None:
    assert await safe_await(_value(1)) == 1
    assert await safe_await([_value(1)]) == [1]
    assert await safe_await(_value(1), _value(2)) == [1, 2]
    assert isinstance(await safe_await(_fail(KeyError()), log_exc=False), KeyError)


async def test_safe_await_raises_when_told_not_to_return() -> None:
    with pytest.raises(KeyError):
        await safe_await(_fail(KeyError()), return_exc=False, log_exc=False)


async def test_safe_await_takes_an_explicit_true_return_exc() -> None:
    assert isinstance(await safe_await(_fail(KeyError()), return_exc=True, log_exc=False), KeyError)
    assert await safe_await([_value(1)], return_exc=True) == [1]
    assert await safe_await(_value(1), _value(2), return_exc=True) == [1, 2]


async def test_gather_helpers_take_an_explicit_false_return_exc() -> None:
    assert await gather_helper(_value(1), return_exc=False) == [1]
    assert await gather_abort([_value(1), _value(2)], return_exc=False) == [1, 2]


async def test_asafe_call_swallows_by_default_and_returns_when_asked() -> None:
    assert await asafe_call(_value(5)) == 5
    assert await asafe_call(_fail(KeyError())) is None
    assert isinstance(await asafe_call(_fail(KeyError()), return_exc=True), KeyError)


async def test_asafe_call_filters_with_include_and_exclude() -> None:
    with pytest.raises(KeyError):
        await asafe_call(_fail(KeyError()), include_exc=ValueError)

    with pytest.raises(FileNotFoundError):
        await asafe_call(_fail(FileNotFoundError()), include_exc=OSError, exclude_exc=FileNotFoundError)

    assert await asafe_call(_fail(PermissionError()), include_exc=OSError, exclude_exc=FileNotFoundError) is None


async def test_asafe_call_always_propagates_keyboard_interrupt() -> None:
    with pytest.raises(KeyboardInterrupt):
        await asafe_call(_fail(KeyboardInterrupt()))


async def test_asafe_call_logs_with_a_sync_or_async_callback(caplog: pytest.LogCaptureFixture) -> None:
    seen: list[BaseException] = []

    async def record(exc: BaseException) -> None:
        """Remember the exception."""
        seen.append(exc)

    await asafe_call(_fail(KeyError()), log_exc=seen.append)
    await asafe_call(_fail(ValueError()), log_exc=record)
    await asafe_call(_fail(OSError()), log_exc=True)
    assert [type(e) for e in seen] == [KeyError, ValueError]
    assert "error in asafe_call" in caplog.text


async def test_asafe_call_raise_exc_logs_then_reraises() -> None:
    seen: list[BaseException] = []

    with pytest.raises(KeyError):
        await asafe_call(_fail(KeyError()), raise_exc=True, log_exc=seen.append)

    assert len(seen) == 1


async def test_asafe_call_rejects_contradictory_arguments() -> None:
    awaitable = _value(1)

    with pytest.raises(TypeError, match="cannot both be True"):
        await asafe_call(awaitable, return_exc=True, raise_exc=True)

    with pytest.raises(TypeError, match="always propagates"):
        await asafe_call(awaitable, exclude_exc=SystemExit)

    await awaitable


async def test_maybe_awaitable_dispatches_on_what_it_gets() -> None:
    assert await maybe_awaitable(_value(1)) == 1
    assert await maybe_awaitable(_value, 2) == 2
    assert await maybe_awaitable(lambda x: x * 3, 3) == 9
    assert await maybe_awaitable(functools.partial(_value, 4)) == 4


async def test_maybe_awaitable_rejects_bad_input() -> None:
    awaitable = _value(1)

    with pytest.raises(TypeError, match="already-created awaitable"):
        await maybe_awaitable(awaitable, 1)

    with pytest.raises(TypeError, match="Expected an Awaitable or Callable"):
        await maybe_awaitable(5)

    await awaitable


async def test_safe_wait_task_tolerates_what_it_is_told_to() -> None:
    assert await safe_wait_task(asyncio.ensure_future(_value(3))) == 3

    cancelled = asyncio.ensure_future(_value(1, delay=5))
    cancelled.cancel()
    assert await safe_wait_task(cancelled) is None

    cancelled = asyncio.ensure_future(_value(1, delay=5))
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await safe_wait_task(cancelled, canceled_ok=False)

    assert await safe_wait_task(asyncio.ensure_future(_fail(KeyError())), exc_ok=True) is None

    with pytest.raises(KeyError):
        await safe_wait_task(asyncio.ensure_future(_fail(KeyError())))


async def test_cancel_task_waits_for_the_cancellation() -> None:
    task = asyncio.ensure_future(_value(1, delay=5))
    await asyncio.sleep(0)
    assert await cancel_task(task) is True
    assert task.cancelled()
    assert await cancel_task(task) is False


async def test_cancel_task_refuses_the_current_task() -> None:
    with pytest.raises(RuntimeError, match="current task"):
        await cancel_task(asyncio.current_task())


async def test_gather_cancel_on_error_of_nothing_is_an_empty_list() -> None:
    assert await _gather_cancel_on_error() == []


async def test_gather_cancel_on_error_runs_a_repeated_awaitable_once() -> None:
    future = asyncio.ensure_future(_value(1))
    assert await _gather_cancel_on_error(future, future) == [1, 1]


async def test_gather_cancel_on_error_handles_already_done_futures() -> None:
    future = asyncio.get_running_loop().create_future()
    future.set_result(9)
    assert await _gather_cancel_on_error(future, _value(1)) == [9, 1]


async def test_gather_cancel_on_error_silences_destroy_pending_only_for_wrapped_awaitables() -> None:
    task = asyncio.ensure_future(_value(1))
    outer = _gather_cancel_on_error(_value(2), task)
    wrapped, passed = outer._children

    assert wrapped._log_destroy_pending is False
    assert passed._log_destroy_pending is True
    assert await outer == [2, 1]


@pytest.mark.skipif(sys.version_info < (3, 14), reason="the awaited-by API is new in 3.14")
async def test_gather_cancel_on_error_links_children_to_the_awaiting_task() -> None:
    outer = _gather_cancel_on_error(_value(1, delay=0.01))
    child = outer._children[0]

    assert asyncio.current_task() in child._asyncio_awaited_by
    assert await outer == [1]
    assert not child._asyncio_awaited_by


async def test_gathering_future_cancel_forwards_to_children() -> None:
    outer = _gather_cancel_on_error(_value(1, delay=5), _value(2, delay=5))
    assert isinstance(outer, _GatheringFuture)
    await asyncio.sleep(0)
    assert outer.cancel("stop") is True
    assert outer.cancel_message == "stop"

    with pytest.raises(asyncio.CancelledError):
        await outer

    assert outer.cancel() is False


async def test_get_fut_loop_returns_the_futures_loop() -> None:
    future = asyncio.get_running_loop().create_future()
    assert _get_fut_loop(future) is asyncio.get_running_loop()
    future.cancel()


def test_log_exc_puts_the_header_index_and_traceback_in_one_record(caplog: pytest.LogCaptureFixture) -> None:
    msg = "boom"
    try:
        raise KeyError(msg)
    except KeyError as e:
        _log_exc("head", traceback.extract_stack(), e, index=2)
        _log_exc(None, None, e, index=0)

    assert "head [awaitable index=2]" in caplog.text
    assert "[awaitable index=0]" in caplog.text
    assert "KeyError" in caplog.text
