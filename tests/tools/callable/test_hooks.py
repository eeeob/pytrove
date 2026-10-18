from __future__ import annotations as _annotations

from collections.abc import Callable

import pytest

from pytrove.callable_tools import middleware


def _raise(exc: BaseException) -> Callable[[], None]:
    """Build a function that raises `exc`."""

    def boom() -> None:
        """Raise the exception."""
        raise exc

    return boom


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


async def test_middleware_never_hands_keyboard_interrupt_to_an_async_on_error() -> None:
    async def interrupted() -> None:
        """Raise `KeyboardInterrupt`."""
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        await middleware(interrupted, on_error=lambda exc: None)()


def test_middleware_accepts_an_explicit_none_hook() -> None:
    assert middleware(lambda: 1, before=None, after=None, on_error=None)() == 1


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
