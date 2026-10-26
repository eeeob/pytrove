from __future__ import annotations as _annotations

import functools
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from pytrove.callable_tools import _internal


def test_internal_protocols_and_type_variables() -> None:
    for proto in (
        _internal._WaitOnErrorDecorator,
        _internal._AwaitOnErrorDecorator,
        _internal._WaitAfterDecorator,
        _internal._AwaitAfterDecorator,
        _internal._ConstantDecorator,
        _internal._LazyCallAll,
    ):
        assert getattr(proto, "_is_protocol", False)

    assert isinstance(_internal._ET_co, TypeVar) and _internal._ET_co.__covariant__
    assert isinstance(_internal._AT_co, TypeVar) and _internal._AT_co.__covariant__
    assert isinstance(_internal._T_contra, TypeVar) and _internal._T_contra.__contravariant__
    assert isinstance(_internal._T_co, TypeVar) and _internal._T_co.__covariant__
    assert _internal._Coro[int] == Coroutine[Any, Any, int]
    assert _internal._ExcLogger == bool | Callable[[BaseException], Any]


async def _coro_func() -> None:
    """Do nothing, asynchronously."""


class _AsyncCall:
    """An object whose `__call__` is a coroutine function."""

    async def __call__(self) -> None:
        """Do nothing, asynchronously."""


def test_is_async_callable_sees_through_wrappers_and_async_call_objects() -> None:
    @functools.wraps(_coro_func)
    def sync_wrapper() -> None:
        """Wrap `_coro_func` without awaiting it."""

    for func in (
        _coro_func,
        functools.partial(_coro_func),
        sync_wrapper,
        _AsyncCall(),
        functools.partial(_AsyncCall()),
    ):
        assert _internal._is_async_callable(func), func

    for func in (print, lambda: None, functools.partial(print), _AsyncCall, object()):
        assert not _internal._is_async_callable(func), func
