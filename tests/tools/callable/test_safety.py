from __future__ import annotations as _annotations

import asyncio
import functools
import inspect
from typing import TYPE_CHECKING

import pytest

from pytrove.callable_tools import raise_if, safe_call

if TYPE_CHECKING:
    from collections.abc import Callable


def _raise(exc: BaseException) -> Callable[[], None]:
    """Build a function that raises `exc`."""

    def boom() -> None:
        """Raise the exception."""
        raise exc

    return boom


def test_safe_call_returns_result_on_success() -> None:
    assert safe_call(lambda x: x + 1, 1) == 2


def test_safe_call_swallows_exception_by_default() -> None:
    assert safe_call(lambda: 1 / 0) is None


def test_safe_call_return_exc() -> None:
    result = safe_call(lambda: 1 / 0, return_exc=True)
    assert isinstance(result, ZeroDivisionError)


def test_safe_call_filters_with_include_and_exclude() -> None:
    with pytest.raises(KeyError):
        safe_call(_raise(KeyError()), include_exc=ValueError)

    with pytest.raises(FileNotFoundError):
        safe_call(_raise(FileNotFoundError()), include_exc=OSError, exclude_exc=FileNotFoundError)

    assert (
        safe_call(_raise(PermissionError()), include_exc=(OSError,), exclude_exc=FileNotFoundError)
        is None
    )


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

    with pytest.raises(TypeError, match="^safe_call: exclude_exc cannot name KeyboardInterrupt"):
        safe_call(print, exclude_exc=(ValueError, KeyboardInterrupt))

    with pytest.raises(TypeError, match="^safe_call: include_exc cannot name SystemExit"):
        safe_call(print, include_exc=SystemExit)


@pytest.mark.parametrize("include_exc", [None, BaseException, asyncio.CancelledError])
def test_safe_call_swallows_a_cancellation_like_any_other_exception(
    include_exc: type[BaseException] | None,
) -> None:
    cancelled = safe_call(
        _raise(asyncio.CancelledError()), include_exc=include_exc, return_exc=True
    )
    assert isinstance(cancelled, asyncio.CancelledError)


def test_raise_if_does_not_crash_on_an_unhashable_result() -> None:
    @raise_if(ValueError, values=[None])
    def returns_list() -> list[int]:
        return [1]

    assert returns_list() == [1]


def test_raise_if_bool_value_sync() -> None:
    @raise_if(ValueError, bool_value=False)
    def check(x: bool) -> bool:
        return x

    assert check(True) is True
    with pytest.raises(ValueError):
        check(False)


def test_raise_if_values_set_sync() -> None:
    @raise_if(ValueError, values=[None, "banned"])
    def check(x: str) -> str:
        return x

    assert check("ok") == "ok"
    for bad in ("banned", None):
        with pytest.raises(ValueError):
            check(bad)


async def test_raise_if_async() -> None:
    @raise_if(ValueError, bool_value=False)
    async def check(x: bool) -> bool:
        return x

    assert await check(True) is True
    with pytest.raises(ValueError):
        await check(False)


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


def test_safe_call_always_propagates_keyboard_interrupt() -> None:
    with pytest.raises(KeyboardInterrupt):
        safe_call(_raise(KeyboardInterrupt()), include_exc=BaseException)


def test_safe_call_logs_by_default_before_reraising(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(KeyError):
        safe_call(_raise(KeyError()), raise_exc=True, log_exc=True)

    assert "error in safe_call" in caplog.text


def test_safe_call_returns_only_the_included_exceptions() -> None:
    returned = safe_call(_raise(KeyError()), return_exc=True, include_exc=(KeyError, ValueError))
    assert isinstance(returned, KeyError)

    with pytest.raises(OSError, match="disk"):
        safe_call(_raise(OSError("disk")), return_exc=True, include_exc=KeyError)


def test_safe_call_logs_only_a_swallowed_exception() -> None:
    seen: list[BaseException] = []

    with pytest.raises(KeyError):
        safe_call(_raise(KeyError()), include_exc=ValueError, log_exc=seen.append)

    assert seen == []


def test_safe_call_lets_a_raising_log_callback_propagate() -> None:
    def broken_logger(exc: BaseException) -> None:
        """Fail while logging."""
        raise RuntimeError from exc

    with pytest.raises(RuntimeError) as info:
        safe_call(_raise(KeyError()), log_exc=broken_logger)

    assert isinstance(info.value.__cause__, KeyError)


def test_safe_call_rejects_a_single_hard_exclude_exc() -> None:
    with pytest.raises(TypeError, match="^safe_call: exclude_exc cannot name SystemExit"):
        safe_call(print, exclude_exc=SystemExit)


def test_raise_if_factory_builds_a_fresh_exception_per_raise() -> None:
    @raise_if(lambda: KeyError("fresh"), always=True)
    def f() -> int:
        """Return one."""
        return 1

    raised: list[BaseException] = []
    for _ in range(2):
        with pytest.raises(KeyError) as info:
            f()
        raised.append(info.value)

    assert raised[0] is not raised[1]


def test_raise_if_resets_a_shared_instance_on_every_raise() -> None:
    shared = ValueError("shared")

    @raise_if(shared, always=True)
    def f() -> int:
        """Return one."""
        return 1

    depths: list[int] = []
    for _ in range(3):
        try:
            raise KeyError  # noqa: TRY301  # An active exception, to become `__context__`.
        except KeyError:
            with pytest.raises(ValueError) as info:
                f()
        assert info.value is shared
        tb, depth = info.value.__traceback__, 0
        while tb is not None:
            tb, depth = tb.tb_next, depth + 1
        depths.append(depth)

    assert depths[0] == depths[1] == depths[2]

    with pytest.raises(ValueError):
        f()

    assert shared.__context__ is None


def test_raise_if_flattens_nested_values() -> None:
    @raise_if(ValueError, values=[[1, [2]], 3])
    def echo(x: int) -> int:
        """Return `x`."""
        return x

    for bad in (1, 2, 3):
        with pytest.raises(ValueError):
            echo(bad)

    assert echo(4) == 4


def test_raise_if_combines_values_and_bool_value() -> None:
    @raise_if(ValueError, bool_value=False, values=["banned"])
    def echo(x: object) -> object:
        """Return `x`."""
        return x

    for bad in ("banned", 0, ""):
        with pytest.raises(ValueError):
            echo(bad)

    assert echo("ok") == "ok"


def test_raise_if_refuses_always_with_values() -> None:
    with pytest.raises(ValueError, match="always=True"):
        raise_if(KeyError(), values=[1], always=True)


def test_raise_if_refuses_a_decorator_that_could_never_raise() -> None:
    with pytest.raises(ValueError, match="nothing can ever raise"):
        raise_if(KeyError("k"))


async def test_raise_if_always_and_values_on_an_async_function() -> None:
    @raise_if(KeyError, always=True)
    async def always() -> int:
        """Return one."""
        return 1

    @raise_if(KeyError, values=[None])
    async def maybe(x: int | None) -> int | None:
        """Return `x`."""
        return x

    with pytest.raises(KeyError):
        await always()

    with pytest.raises(KeyError):
        await maybe(None)

    assert await maybe(1) == 1
    assert always.__name__ == "always"
    assert always.__wrapped__ is not None
    assert inspect.iscoroutinefunction(always)


class _AsyncCallable:
    """An object whose `__call__` is a coroutine function."""

    async def __call__(self, x: int | None) -> int | None:
        """Return `x`."""
        return x


async def test_raise_if_sees_an_async_callable_object() -> None:
    checked = raise_if(KeyError, values=[None])(_AsyncCallable())
    assert inspect.iscoroutinefunction(checked)

    with pytest.raises(KeyError):
        await checked(None)

    assert await checked(2) == 2


async def test_raise_if_does_not_await_a_plain_result_of_an_async_looking_wrapper() -> None:
    async def source() -> int:
        """Return one."""
        return 1

    checked = raise_if(KeyError, values=[None])(functools.wraps(source)(lambda: 5))
    assert await checked() == 5
