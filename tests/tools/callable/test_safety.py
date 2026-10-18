from __future__ import annotations as _annotations

from collections.abc import Callable

import pytest

from pytrove.callable_tools import raise_if, safe_call


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
    with pytest.raises(ValueError):
        check("banned")


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
