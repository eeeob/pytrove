"""Combining, adapting and annotating callables."""

from __future__ import annotations as _annotations

import functools
from typing import TYPE_CHECKING, Any, overload

from .._internal import _ignore_arguments
from ._internal import _is_async_callable

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..typings import _False, _FT, _P, _T, _True
    from ._internal import _ConstantDecorator, _Coro, _LazyCallAll


@overload
def set_func_attrs(func: _FT, **kw: Any) -> _FT: ...
@overload
def set_func_attrs(func: None = None, **kw: Any) -> Callable[[_FT], _FT]: ...
def set_func_attrs(func: Callable[..., Any] | None = None, **kw: Any) -> Any:
    """Set attributes on a function, directly or as a decorator.

    Args:
        func: The function; omit it to get a decorator.
        **kw: The attributes to set.

    Returns:
        The function itself, or a decorator when `func` is omitted.

    Example:
        >>> @set_func_attrs(tag="x")
        ... def f(): ...
        >>> f.tag
        'x'
    """

    def updater(f: _FT) -> _FT:
        """Set the attributes on `f`.

        Args:
            f: The function.

        Returns:
            `f` itself.
        """
        for k, v in kw.items():
            setattr(f, k, v)

        return f

    return updater if func is None else updater(func)


@overload
def call_all(*funcs: Callable[[], _T], lazy: _False = False) -> tuple[_T, ...]: ...
@overload
def call_all(*funcs: Callable[[], _T], lazy: _True) -> _LazyCallAll[_T]: ...
def call_all(*funcs: Callable[[], Any], lazy: bool = False) -> Any:
    """Call zero-argument callables in order and collect their results.

    A callable that raises stops the rest. With `lazy`, nothing runs yet: the
    result is `call_all` again with these functions prepended, so batches can
    be built up and run later by calling it with no arguments.

    Args:
        *funcs: The callables.
        lazy: Whether to capture instead of calling.

    Returns:
        The results in order, or the lazy callable.

    Example:
        >>> call_all(lambda: 1, lambda: 2)
        (1, 2)
        >>> batch = call_all(lambda: 1, lazy=True)
        >>> batch(lambda: 2)
        (1, 2)
    """
    if lazy:
        return functools.partial(call_all, *funcs)

    return tuple(func() for func in funcs)


def juxt(*funcs: Callable[..., _T]) -> Callable[..., tuple[_T, ...]]:
    """Fan one call out to many functions.

    The functions need not share one signature (`str.upper` and `len` take
    different parameter types), so the result's parameters are not checked
    statically; its element type is the union of their result types.

    Args:
        *funcs: The functions, all called with the same arguments.

    Returns:
        A callable returning their results in order.

    Example:
        >>> juxt(str.upper, len)("ab")
        ('AB', 2)
    """

    def fanned(*args: Any, **kwargs: Any) -> tuple[_T, ...]:
        """Call every function with these arguments.

        Args:
            *args: Positional arguments for each function.
            **kwargs: Keyword arguments for each function.

        Returns:
            The results in order.
        """
        return tuple(func(*args, **kwargs) for func in funcs)

    return fanned


def ignore_arguments(func: Callable[[], _T]) -> Callable[..., _T]:
    """Wrap a zero-argument function so it accepts and ignores any arguments.

    Args:
        func: The function.

    Returns:
        A wrapper calling `func()` whatever it is passed.
    """
    return _ignore_arguments(func)


# `value` omitted has its own arms typed `None`: a `None` default cannot solve `_T`. A coroutine
# function comes first, since its wrapper stays a coroutine function.
@overload
def return_constant(func: Callable[_P, _Coro[Any]]) -> Callable[_P, _Coro[None]]: ...
@overload
def return_constant(func: Callable[_P, Any]) -> Callable[_P, None]: ...
@overload
def return_constant(func: Callable[_P, _Coro[Any]], *, value: _T) -> Callable[_P, _Coro[_T]]: ...
@overload
def return_constant(func: Callable[_P, Any], *, value: _T) -> Callable[_P, _T]: ...
@overload
def return_constant(func: None = None) -> _ConstantDecorator[None]: ...
@overload
def return_constant(func: None = None, *, value: _T) -> _ConstantDecorator[_T]: ...
def return_constant(func: Callable[_P, Any] | None = None, *, value: Any = None) -> Any:
    """Wrap a function so it runs as usual but always returns `value`.

    An async function (as `middleware` decides it) gets an async wrapper that
    awaits it before returning `value`.

    Args:
        func: The function; omit it to get a decorator.
        value: What the wrapper returns.

    Returns:
        The wrapper, or a decorator when `func` is omitted.

    Example:
        >>> return_constant(print, value=True)("hi")
        hi
        True
    """
    if func is None:
        return functools.partial(return_constant, value=value)

    if _is_async_callable(func):

        async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
            """Await `func` and return `value` instead of its result."""
            await func(*args, **kwargs)
            return value

    else:

        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
            """Call `func` and return `value` instead of its result."""
            func(*args, **kwargs)
            return value

    return functools.wraps(func)(wrapper)


__all__ = (
    "set_func_attrs",
    "call_all",
    "juxt",
    "ignore_arguments",
    "return_constant",
)
