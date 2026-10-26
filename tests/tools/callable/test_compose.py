from __future__ import annotations as _annotations

import inspect

import pytest

from pytrove.callable_tools import call_all, ignore_arguments, juxt, return_constant, set_func_attrs


def test_set_func_attrs_as_decorator() -> None:
    @set_func_attrs(tag="hello")
    def f() -> None:
        pass

    assert f.tag == "hello"


def test_set_func_attrs_direct_call() -> None:
    def f() -> None:
        pass

    result = set_func_attrs(f, tag="direct")
    assert result is f
    assert f.tag == "direct"


def test_juxt_fans_one_call_across_every_function() -> None:
    assert juxt(str.upper, str.lower, len)("Ab") == ("AB", "ab", 2)


def test_juxt_passes_through_args_and_kwargs() -> None:
    fanned = juxt(
        lambda a, b, c=0: a + b + c,
        lambda a, b, c=0: a * b * (c or 1),
    )
    assert fanned(2, 3, c=4) == (9, 24)


def test_juxt_with_no_functions_returns_an_empty_tuple() -> None:
    assert juxt()(1, 2, 3) == ()


def test_juxt_result_is_reusable() -> None:
    fanned = juxt(len, lambda s: s[0])
    assert fanned("abc") == (3, "a")
    assert fanned("xy") == (2, "x")


def test_juxt_does_not_swallow_a_raising_function() -> None:
    with pytest.raises(ZeroDivisionError):
        juxt(len, lambda _: 1 / 0)("abc")


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


def test_set_func_attrs_sets_several_attributes_or_none() -> None:
    def f() -> None:
        """Do nothing."""

    assert set_func_attrs(f, a=1, b="two") is f
    assert (f.a, f.b) == (1, "two")
    assert set_func_attrs()(f) is f


def test_call_all_stops_at_the_first_raise() -> None:
    calls: list[int] = []

    def boom() -> None:
        """Fail."""
        raise KeyError

    with pytest.raises(KeyError):
        call_all(lambda: calls.append(1), boom, lambda: calls.append(3))

    assert calls == [1]


def test_call_all_with_nothing_to_call() -> None:
    assert call_all() == ()
    assert call_all(lazy=True)() == ()


def test_ignore_arguments_keeps_the_function_identity() -> None:
    def named() -> str:
        """Return a constant."""
        return "ok"

    wrapped = ignore_arguments(named)
    assert wrapped.__name__ == "named"
    assert wrapped.__wrapped__ is named


def test_return_constant_defaults_to_none_and_keeps_the_function_identity() -> None:
    calls: list[int] = []

    def record(x: int) -> int:
        """Record `x`."""
        calls.append(x)
        return x

    wrapped = return_constant(record)
    assert wrapped(1) is None
    assert calls == [1]
    assert wrapped.__name__ == "record"
    assert wrapped.__wrapped__ is record
    assert return_constant()(record)(2) is None
    assert calls == [1, 2]


async def test_return_constant_awaits_a_coroutine_function() -> None:
    ran: list[int] = []

    async def work(x: int) -> int:
        """Record `x`."""
        ran.append(x)
        return x

    wrapped = return_constant(work, value="done")
    assert inspect.iscoroutinefunction(wrapped)
    assert await wrapped(1) == "done"
    assert ran == [1]

    @return_constant
    async def decorated() -> int:
        """Record a call."""
        ran.append(2)
        return 2

    assert await decorated() is None
    assert ran == [1, 2]


async def test_return_constant_sees_an_async_callable_object() -> None:
    class Work:
        """An object whose `__call__` is a coroutine function."""

        async def __call__(self) -> int:
            """Return one."""
            return 1

    wrapped = return_constant(Work(), value=5)
    assert inspect.iscoroutinefunction(wrapped)
    assert await wrapped() == 5
