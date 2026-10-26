from __future__ import annotations as _annotations

import asyncio
import functools
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from pytrove.async_tools import asafe_call, maybe_awaitable, safe_await


async def _value(v: Any, delay: float = 0) -> Any:
    """Return `v` after `delay` seconds."""
    await asyncio.sleep(delay)
    return v


async def _fail(exc: BaseException, delay: float = 0) -> None:
    """Raise `exc` after `delay` seconds."""
    await asyncio.sleep(delay)
    raise exc


async def test_safe_await_logs_a_single_failure_without_an_index(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert isinstance(await safe_await(_fail(KeyError("one"))), KeyError)
    assert "error in safe_await\n" in caplog.text
    assert "awaitable index" not in caplog.text


async def test_safe_await_logs_each_failure_of_several_with_its_index(
    caplog: pytest.LogCaptureFixture,
) -> None:
    results = await safe_await(_value(1), _fail(KeyError("two")))

    assert results[0] == 1
    assert isinstance(results[1], KeyError)
    assert "error in safe_await [awaitable index=1]" in caplog.text


async def test_safe_await_of_nothing_is_an_empty_list() -> None:
    assert await safe_await() == []


async def test_safe_await_single_returns_exception_by_default() -> None:
    result = await safe_await(_fail(ValueError("boom")), log_exc=False)
    assert isinstance(result, ValueError)


async def test_safe_await_raises_when_return_exc_false() -> None:
    with pytest.raises(ValueError, match="boom"):
        await safe_await(_fail(ValueError("boom")), return_exc=False, log_exc=False)


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


async def test_asafe_call_swallows_by_default_and_returns_when_asked() -> None:
    assert await asafe_call(_value(5)) == 5
    assert await asafe_call(_fail(KeyError())) is None
    assert isinstance(await asafe_call(_fail(KeyError()), return_exc=True), KeyError)


async def test_asafe_call_filters_with_include_and_exclude() -> None:
    with pytest.raises(KeyError):
        await asafe_call(_fail(KeyError()), include_exc=ValueError)

    with pytest.raises(FileNotFoundError):
        await asafe_call(
            _fail(FileNotFoundError()), include_exc=OSError, exclude_exc=FileNotFoundError
        )

    assert (
        await asafe_call(
            _fail(PermissionError()), include_exc=OSError, exclude_exc=FileNotFoundError
        )
        is None
    )


async def test_asafe_call_always_propagates_keyboard_interrupt() -> None:
    with pytest.raises(KeyboardInterrupt):
        await asafe_call(_fail(KeyboardInterrupt()))


async def test_asafe_call_swallows_a_cancellation_by_default() -> None:
    result = await asafe_call(_fail(asyncio.CancelledError()), return_exc=True)

    assert isinstance(result, asyncio.CancelledError)


async def test_asafe_call_swallows_a_cancellation_named_in_include_exc() -> None:
    task = asyncio.create_task(asyncio.sleep(10))
    task.cancel()
    await asyncio.sleep(0)

    result = await asafe_call(task, include_exc=asyncio.CancelledError, return_exc=True)

    assert isinstance(result, asyncio.CancelledError)


async def test_safe_await_never_returns_a_cancellation() -> None:
    with pytest.raises(asyncio.CancelledError):
        await safe_await(_fail(asyncio.CancelledError()))


async def test_asafe_call_logs_with_a_sync_or_async_callback(
    caplog: pytest.LogCaptureFixture,
) -> None:
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

    with pytest.raises(TypeError, match="^asafe_call: exclude_exc cannot name SystemExit"):
        await asafe_call(awaitable, exclude_exc=SystemExit)

    with pytest.raises(TypeError, match="^asafe_call: include_exc cannot name KeyboardInterrupt"):
        await asafe_call(awaitable, include_exc=KeyboardInterrupt)

    await awaitable


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
            result = await maybe_awaitable(
                awaitable_or_callable, *args, return_exc=return_exc, log_exc=False, **kwargs
            )
            assert isinstance(result, ValueError)
        else:
            with pytest.raises(ValueError, match="a|k"):
                await maybe_awaitable(
                    awaitable_or_callable, *args, return_exc=return_exc, log_exc=False, **kwargs
                )


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


async def test_safe_await_skips_none_and_flattens_any_depth() -> None:
    assert await safe_await([_value(1), None]) == [1]
    assert await safe_await([[_value(1)], ([_value(2), None],)], _value(3)) == [1, 2, 3]


async def test_safe_await_treats_a_returned_exception_as_a_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    returned = ValueError("v")

    assert await safe_await(_value(returned), return_exc=False) is returned
    assert await safe_await(_value(returned)) is returned
    assert "error in safe_await" not in caplog.text


async def test_asafe_call_takes_a_tuple_of_exceptions_to_swallow() -> None:
    assert await asafe_call(_fail(KeyError()), include_exc=(ValueError, KeyError)) is None

    with pytest.raises(OSError):  # noqa: PT011 - the awaitable raises a bare `OSError`
        await asafe_call(_fail(OSError()), include_exc=(ValueError, KeyError))


@pytest.mark.parametrize("include_exc", [KeyError, (KeyError, ValueError)])
async def test_asafe_call_returns_an_included_exception(
    include_exc: type[Exception] | tuple[type[Exception], ...],
) -> None:
    result = await asafe_call(_fail(KeyError("k")), return_exc=True, include_exc=include_exc)
    assert isinstance(result, KeyError)


async def test_asafe_call_lets_an_error_of_the_log_callback_propagate_with_context() -> None:
    original = KeyError("original")

    def broken_logger(_exc: BaseException) -> None:
        """Fail while logging."""
        msg = "logger broke"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="logger broke") as caught:
        await asafe_call(_fail(original), log_exc=broken_logger)

    assert caught.value.__context__ is original


async def test_asafe_call_swallows_a_cancelled_task_by_default() -> None:
    task = asyncio.create_task(asyncio.sleep(10))
    task.cancel()
    await asyncio.sleep(0)

    assert isinstance(await asafe_call(task, return_exc=True), asyncio.CancelledError)


async def test_maybe_awaitable_runs_a_sync_callable_in_the_given_executor() -> None:
    def thread_name() -> str:
        """Return the name of the thread this runs on."""
        return threading.current_thread().name

    with ThreadPoolExecutor(1, thread_name_prefix="maybe") as executor:
        assert (await maybe_awaitable(thread_name, executor=executor)).startswith("maybe")


async def test_maybe_awaitable_logs_a_failure_when_asked(caplog: pytest.LogCaptureFixture) -> None:
    def boom() -> None:
        """Fail."""
        raise KeyError

    assert isinstance(await maybe_awaitable(boom, return_exc=True), KeyError)
    assert "error in to_thread" in caplog.text
    caplog.clear()

    assert isinstance(await maybe_awaitable(_fail(KeyError()), return_exc=True), KeyError)
    assert "error in safe_await" in caplog.text
