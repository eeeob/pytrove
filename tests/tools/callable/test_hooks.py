from __future__ import annotations as _annotations

import asyncio
import functools
import inspect
from typing import TYPE_CHECKING, Any

import pytest

from pytrove.callable_tools import middleware

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


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


async def test_middleware_hands_a_cancellation_to_an_async_on_error() -> None:
    async def cancelled() -> str:
        """Raise `asyncio.CancelledError`."""
        raise asyncio.CancelledError

    seen: list[BaseException] = []

    def on_error(exc: BaseException) -> str:
        """Record `exc` and recover."""
        seen.append(exc)
        return "recovered"

    assert await middleware(cancelled, on_error=on_error)() == "recovered"
    assert len(seen) == 1
    assert isinstance(seen[0], asyncio.CancelledError)


def test_middleware_hands_a_cancellation_to_a_sync_on_error() -> None:
    wrapped = middleware(_raise(asyncio.CancelledError()), on_error=type)

    assert wrapped() is asyncio.CancelledError


def test_middleware_lets_a_hook_exception_propagate() -> None:
    def boom(*_: object) -> None:
        """Raise `KeyError` whatever the arguments."""
        raise KeyError

    with pytest.raises(KeyError):
        middleware(lambda: 1, before=boom, on_error=lambda exc: "swallowed")()

    with pytest.raises(KeyError):
        middleware(lambda: 1, after=boom, on_error=lambda exc: "swallowed")()


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

    for key in ("before", "after", "on_error"):
        with pytest.raises(TypeError, match=f"argument '{key}' must be callable"):
            middleware(print, **{key: 5})


async def _resolve(value: Any) -> Any:
    """Await `value` when it is awaitable, so one test drives a sync or an async wrapper."""
    return await value if inspect.isawaitable(value) else value


def _make(is_async: bool, func: Callable[..., Any]) -> Callable[..., Any]:
    """Return `func` itself, or a coroutine function calling it."""
    if not is_async:
        return func

    async def coro_func(*args: Any, **kwargs: Any) -> Any:
        """Call `func`."""
        return func(*args, **kwargs)

    return coro_func


def _fail(*_: object, **__: object) -> None:
    """Raise `KeyError` whatever the arguments."""
    raise KeyError


both = pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])


@both
async def test_middleware_runs_every_hook_in_order(is_async: bool) -> None:
    calls: list[str] = []

    def func(x: int) -> int:
        """Record the call and fail."""
        calls.append("func")
        raise KeyError(x)

    def before(x: int) -> None:
        """Record the call."""
        calls.append("before")

    def on_error(exc: BaseException, x: int) -> int:
        """Record the call and recover."""
        calls.append("on_error")
        return x * 10

    def after(result: int, x: int) -> int:
        """Record the call and pass `result` on."""
        calls.append("after")
        return result + 1

    wrapped = middleware(
        _make(is_async, func),
        before=_make(is_async, before),
        on_error=_make(is_async, on_error),
        after=_make(is_async, after),
    )
    assert await _resolve(wrapped(2)) == 21
    assert calls == ["before", "func", "on_error", "after"]


@both
async def test_middleware_after_receives_the_on_error_replacement(is_async: bool) -> None:
    seen: list[object] = []

    def after(result: object) -> object:
        """Record `result`."""
        seen.append(result)
        return result

    wrapped = middleware(
        _make(is_async, _fail), on_error=lambda exc: "recovered", after=_make(is_async, after)
    )
    assert await _resolve(wrapped()) == "recovered"
    assert seen == ["recovered"]


@both
async def test_middleware_hooks_receive_positional_and_keyword_arguments(is_async: bool) -> None:
    seen: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def record(name: str) -> Callable[..., None]:
        """Build a hook recording the call's arguments under `name`."""

        def hook(*args: object, **kwargs: object) -> None:
            """Record the arguments, without the leading result or exception."""
            seen.append((name, args if name == "before" else args[1:], kwargs))

        return hook

    wrapped = middleware(
        _make(is_async, _fail),
        before=_make(is_async, record("before")),
        on_error=_make(is_async, record("on_error")),
        after=_make(is_async, record("after")),
    )
    await _resolve(wrapped(1, 2, key="v"))
    assert seen == [
        ("before", (1, 2), {"key": "v"}),
        ("on_error", (1, 2), {"key": "v"}),
        ("after", (1, 2), {"key": "v"}),
    ]


@both
async def test_middleware_a_raising_before_stops_the_call(is_async: bool) -> None:
    calls: list[str] = []
    wrapped = middleware(
        _make(is_async, lambda: calls.append("func")),
        before=_make(is_async, _fail),
        on_error=lambda exc: "swallowed",
    )

    with pytest.raises(KeyError):
        await _resolve(wrapped())

    assert calls == []


@both
@pytest.mark.parametrize("key", ["before", "after", "on_error"])
async def test_middleware_lets_each_hook_exception_propagate(is_async: bool, key: str) -> None:
    func = (lambda: 1 / 0) if key == "on_error" else (lambda: 1)
    wrapped = middleware(_make(is_async, func), **{key: _make(is_async, _fail)})

    with pytest.raises(KeyError):
        await _resolve(wrapped())


@both
@pytest.mark.parametrize("exc_type", [SystemExit, KeyboardInterrupt])
async def test_middleware_never_hands_hard_exceptions_to_on_error(
    is_async: bool, exc_type: type[BaseException]
) -> None:
    seen: list[BaseException] = []
    wrapped = middleware(_make(is_async, _raise(exc_type())), on_error=seen.append)

    with pytest.raises(exc_type):
        await _resolve(wrapped())

    assert seen == []


@both
async def test_middleware_hands_generator_exit_to_on_error(is_async: bool) -> None:
    wrapped = middleware(_make(is_async, _raise(GeneratorExit())), on_error=lambda exc: "seen")
    assert await _resolve(wrapped()) == "seen"


async def test_middleware_as_a_decorator_on_a_coroutine_function() -> None:
    async def on_error(exc: BaseException) -> str:
        """Recover asynchronously."""
        return "recovered"

    @middleware(on_error=on_error, after=lambda result: result.upper())
    async def broken() -> str:
        """Fail."""
        raise KeyError

    assert inspect.iscoroutinefunction(broken)
    assert await broken() == "RECOVERED"


def test_middleware_as_a_decorator_with_on_error_and_after() -> None:
    @middleware(on_error=lambda exc, x: -1, after=lambda result, x: result * 2)
    def invert(x: float) -> float:
        """Return the inverse of `x`."""
        return 1 / x

    assert invert(4) == 0.5
    assert invert(0) == -2


@pytest.mark.parametrize(
    ("kw", "match"),
    [({"around": print}, "unexpected keyword"), ({"before": 5}, "must be callable")],
)
def test_middleware_checks_its_keywords_before_returning_a_decorator(
    kw: dict[str, Any], match: str
) -> None:
    with pytest.raises(TypeError, match=match):
        middleware(**kw)


@both
def test_middleware_keeps_the_function_identity(is_async: bool) -> None:
    def named() -> int:
        """Return one."""
        return 1

    func = _make(is_async, named)
    wrapped = middleware(func, after=lambda result: result)
    assert wrapped.__name__ == func.__name__
    assert wrapped.__wrapped__ is func
    assert inspect.iscoroutinefunction(wrapped) is is_async


async def _async_double(x: int) -> int:
    """Double `x`, asynchronously."""
    return x * 2


@functools.wraps(_async_double)
def _returns_a_coroutine(x: int) -> Awaitable[int]:
    """Return `_async_double`'s coroutine from a sync function."""
    return _async_double(x)


class _AsyncCallable:
    """An object whose `__call__` is a coroutine function."""

    async def __call__(self, x: int) -> int:
        """Fail for a negative `x`, else double it."""
        if x < 0:
            raise KeyError(x)
        return x * 2


@pytest.mark.parametrize(
    "func",
    [
        functools.partial(_async_double),
        _returns_a_coroutine,
        _AsyncCallable(),
        functools.partial(_AsyncCallable()),
    ],
    ids=["partial", "wrapped", "async_call", "partial_of_async_call"],
)
async def test_middleware_sees_an_async_function_through_its_wrappers(
    func: Callable[[int], Awaitable[int]],
) -> None:
    wrapped = middleware(func, on_error=lambda exc, x: "handled", after=lambda result, x: result)
    assert inspect.iscoroutinefunction(wrapped)
    assert await wrapped(3) == 6


async def test_middleware_hands_an_async_call_objects_error_to_on_error() -> None:
    wrapped = middleware(_AsyncCallable(), on_error=lambda exc, x: "handled")
    assert await wrapped(-1) == "handled"


async def test_middleware_does_not_await_a_plain_result_of_an_async_looking_wrapper() -> None:
    seen: list[BaseException] = []
    sync_wrapper = functools.wraps(_async_double)(lambda x: 5)
    wrapped = middleware(sync_wrapper, on_error=seen.append)
    assert await wrapped(1) == 5
    assert seen == []


@pytest.mark.parametrize("key", ["before", "after", "on_error"])
def test_middleware_refuses_an_async_hook_on_a_sync_function(key: str) -> None:
    async def hook(*_: object) -> None:
        """Do nothing, asynchronously."""

    with pytest.raises(TypeError, match=f"argument '{key}' is async"):
        middleware(lambda: 1, **{key: hook})

    with pytest.raises(TypeError, match=f"argument '{key}' is async"):
        middleware(**{key: hook})(lambda: 1)

    with pytest.raises(TypeError, match=f"argument '{key}' is async"):
        middleware(lambda: 1, **{key: _AsyncCallable()})
