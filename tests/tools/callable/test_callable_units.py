from __future__ import annotations as _annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any, TypeVar

import pytest

from pytrove.callable_tools import (
    await_sync,
    call_all,
    ignore_arguments,
    middleware,
    raise_if,
    return_constant,
    run_awaitable_sync,
    safe_call,
)
from pytrove.callable_tools import _internal


def _raise(exc: BaseException) -> Callable[[], None]:
    """Build a function that raises `exc`."""

    def boom() -> None:
        """Raise the exception."""
        raise exc

    return boom


def test_safe_call_filters_with_include_and_exclude() -> None:
    with pytest.raises(KeyError):
        safe_call(_raise(KeyError()), include_exc=ValueError)

    with pytest.raises(FileNotFoundError):
        safe_call(_raise(FileNotFoundError()), include_exc=OSError, exclude_exc=FileNotFoundError)

    assert safe_call(_raise(PermissionError()), include_exc=(OSError,), exclude_exc=FileNotFoundError) is None


def test_safe_call_always_propagates_system_exit() -> None:
    with pytest.raises(SystemExit):
        safe_call(_raise(SystemExit()))


def test_safe_call_logs_and_can_reraise(caplog: pytest.LogCaptureFixture) -> None:
    seen: list[BaseException] = []
    safe_call(_raise(KeyError()), log_exc=True)
    assert "error in safe_call" in caplog.text

    with pytest.raises(KeyError):
        safe_call(_raise(KeyError()), raise_exc=True, log_exc=seen.append)

    assert len(seen) == 1


def test_safe_call_passes_arguments_through() -> None:
    assert safe_call(lambda a, b=0: a + b, 1, b=2) == 3


def test_safe_call_rejects_contradictory_arguments() -> None:
    with pytest.raises(TypeError, match="cannot both be True"):
        safe_call(print, return_exc=True, raise_exc=True)

    with pytest.raises(TypeError, match="always propagates"):
        safe_call(print, exclude_exc=(ValueError, KeyboardInterrupt))


def test_raise_if_always_and_factory() -> None:
    @raise_if(lambda: KeyError("fresh"), always=True)
    def f() -> int:
        """Return one."""
        return 1

    with pytest.raises(KeyError):
        f()


def test_raise_if_refuses_always_with_conditions() -> None:
    with pytest.raises(ValueError, match="always=True"):
        raise_if(KeyError(), bool_value=True, always=True)


def test_raise_if_keeps_the_function_name() -> None:
    @raise_if(KeyError(), values=[None])
    def named() -> int:
        """Return two."""
        return 2

    assert named.__name__ == "named"
    assert named() == 2


def test_middleware_runs_hooks_around_a_sync_function() -> None:
    calls: list[str] = []
    wrapped = middleware(
        lambda x: x * 2,
        before=lambda x: calls.append(f"before {x}"),
        after=lambda result, x: result + 1,
    )
    assert wrapped(3) == 7
    assert calls == ["before 3"]


def test_middleware_on_error_replaces_the_result() -> None:
    wrapped = middleware(lambda: 1 / 0, on_error=lambda exc: type(exc).__name__)
    assert wrapped() == "ZeroDivisionError"

    with pytest.raises(ZeroDivisionError):
        middleware(lambda: 1 / 0)()


def test_middleware_never_hands_keyboard_interrupt_to_on_error() -> None:
    with pytest.raises(KeyboardInterrupt):
        middleware(_raise(KeyboardInterrupt()), on_error=lambda exc: None)()


async def test_middleware_awaits_sync_or_async_hooks_around_a_coroutine() -> None:
    async def double(x: int) -> int:
        """Double `x`."""
        return x * 2

    async def after(result: int, x: int) -> int:
        """Add one."""
        return result + 1

    assert await middleware(double, before=lambda x: None, after=after)(3) == 7

    async def broken() -> None:
        """Fail."""
        raise KeyError

    assert await middleware(broken, on_error=lambda exc: "handled")() == "handled"

    with pytest.raises(KeyError):
        await middleware(broken)()


def test_middleware_as_a_decorator_and_its_argument_checks() -> None:
    @middleware(after=lambda result: result * 10)
    def five() -> int:
        """Return five."""
        return 5

    assert five() == 50

    with pytest.raises(TypeError, match="unexpected keyword"):
        middleware(print, around=print)

    with pytest.raises(TypeError, match="must be callable"):
        middleware(print, before=5)


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


def test_call_all_runs_in_order_or_lazily() -> None:
    calls: list[int] = []
    assert call_all(lambda: calls.append(1) or 1, lambda: 2) == (1, 2)
    lazy = call_all(lambda: 3, lazy=True)
    more = lazy(lambda: 4, lazy=True)
    assert calls == [1]
    assert more() == (3, 4)
    assert lazy(lambda: 5) == (3, 5)


def test_ignore_arguments_drops_whatever_it_is_given() -> None:
    assert ignore_arguments(lambda: "ok")(1, 2, x=3) == "ok"


def test_return_constant_directly_and_as_a_decorator() -> None:
    calls: list[int] = []
    assert return_constant(calls.append, value=True)(5) is True
    assert calls == [5]

    @return_constant(value="fixed")
    def anything(x: int) -> int:
        """Return `x`."""
        return x

    assert anything(1) == "fixed"


def test_internal_protocols_and_type_variables() -> None:
    for proto in (
        _internal._WaitOnErrorDecorator, _internal._AwaitOnErrorDecorator,
        _internal._WaitAfterDecorator, _internal._AwaitAfterDecorator, _internal._LazyCallAll,
    ):
        assert getattr(proto, "_is_protocol", False)

    assert isinstance(_internal._ET, TypeVar) and _internal._ET.__covariant__
    assert isinstance(_internal._AT, TypeVar) and _internal._AT.__covariant__
    assert _internal._Coro is not None
    assert _internal._ExcLogger is not None
