"""Calling with exceptions swallowed, and raising on chosen results."""

from __future__ import annotations as _annotations

import functools
import logging
from typing import TYPE_CHECKING, Any, overload

from .._internal import _HARD_PROPAGATE, _check_swallow_options, _is_swallowed
from ..iter_tools import iter_flat_cont
from ..async_tools import call_sync_or_await
from ._internal import _is_async_callable

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable

    from .._internal import _ExcFilter
    from ..typings import NestedContainer, _ExcT, _False, _P, _T, _True
    from ._internal import _ExcLogger

log = logging.getLogger(__name__)


# Every arm names both flags: each takes `**kwargs: Any`, so an arm without a flag would let
# `**kwargs` absorb it and type-check `return_exc=True, raise_exc=True`, a runtime `TypeError`.
@overload
def safe_call(
    func: Callable[..., _T],
    *args: Any,
    return_exc: _False = False,
    raise_exc: _True,
    include_exc: _ExcFilter = None,
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
    **kwargs: Any,
) -> _T: ...
@overload
def safe_call(
    func: Callable[..., _T],
    *args: Any,
    return_exc: _True,
    raise_exc: _False = False,
    include_exc: type[_ExcT],
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
    **kwargs: Any,
) -> _T | _ExcT: ...
@overload
def safe_call(
    func: Callable[..., _T],
    *args: Any,
    return_exc: _True,
    raise_exc: _False = False,
    include_exc: tuple[type[_ExcT], ...],
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
    **kwargs: Any,
) -> _T | _ExcT: ...
@overload
def safe_call(
    func: Callable[..., _T],
    *args: Any,
    return_exc: _True,
    raise_exc: _False = False,
    include_exc: _ExcFilter = None,
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
    **kwargs: Any,
) -> _T | BaseException: ...
@overload
def safe_call(
    func: Callable[..., _T],
    *args: Any,
    return_exc: _False = False,
    raise_exc: _False = False,
    include_exc: _ExcFilter = None,
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
    **kwargs: Any,
) -> _T | None: ...
def safe_call(
    func: Callable[..., Any],
    *args: Any,
    return_exc: bool = False,
    raise_exc: bool = False,
    include_exc: _ExcFilter = None,
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
    **kwargs: Any,
) -> Any:
    """Call `func(*args, **kwargs)`, swallowing what it raises.

    `exclude_exc` always propagates and wins over `include_exc`
    (`include_exc=OSError, exclude_exc=FileNotFoundError` swallows every
    `OSError` but that one). `SystemExit` and `KeyboardInterrupt` always
    propagate. `log_exc` fires only for a swallowed exception, and an error
    it raises itself propagates.

    Args:
        func: The callable.
        *args: Its positional arguments.
        return_exc: Whether to return a swallowed exception instead of `None`.
        raise_exc: Whether to re-raise after `log_exc` ran, for the logging alone.
        include_exc: The exceptions to swallow; `None` for all.
        exclude_exc: The exceptions that always propagate.
        log_exc: `True` to log a swallowed exception at error level, or a callback receiving it.
        **kwargs: Its keyword arguments.

    Returns:
        The result, or `None` / the exception after a swallowed failure.

    Raises:
        TypeError: If `return_exc` and `raise_exc` are both set, or `include_exc`
            or `exclude_exc` names `SystemExit` or `KeyboardInterrupt`.
        BaseException: Whatever is not swallowed, or anything when `raise_exc` is set.

    Example:
        >>> safe_call(int, "x") is None
        True
        >>> safe_call(int, "x", return_exc=True)
        ValueError("invalid literal for int() with base 10: 'x'")
        >>> safe_call(int, "x", include_exc=KeyError)
        Traceback (most recent call last):
        ValueError: invalid literal for int() with base 10: 'x'
    """
    _check_swallow_options("safe_call", return_exc, raise_exc, include_exc, exclude_exc)

    try:
        return func(*args, **kwargs)
    except _HARD_PROPAGATE as exc:
        raise exc
    except BaseException as e:
        if not _is_swallowed(e, include_exc, exclude_exc):
            raise e

        if log_exc:
            if callable(log_exc):
                log_exc(e)
            else:
                log.error("error in safe_call(%r)", func, exc_info=e)

        if raise_exc:
            raise e

        if return_exc:
            return e

    return None


def raise_if(
    exc: BaseException | Callable[[], BaseException],
    bool_value: bool | None = None,
    values: NestedContainer[Hashable | None] = None,
    always: bool = False,
) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    """Decorate a sync or async function to raise when its result matches.

    A result raises when `always` is set, when it is one of `values`, or when
    its truth value equals `bool_value`. `values` is flattened, `None` leaves included,
    and an unhashable result never matches it.
    A function is async as `middleware` decides it; its result is awaited when awaitable.

    An exception instance is shared by every raise: each one clears its
    `__traceback__` and `__context__` first, so they do not pile up across raises.
    Pass a class or factory when the decorated function may raise from several
    threads at once.

    Args:
        exc: The exception to raise, or a class or factory building a fresh one each time.
        bool_value: The truth value that raises; `None` to ignore truthiness.
        values: The results that raise.
        always: Whether every result raises.

    Returns:
        The decorator.

    Raises:
        ValueError: If `always` is combined with `bool_value` or `values`, or if
            none of the three is given, so nothing could ever raise.

    Example:
        >>> @raise_if(ValueError("empty"), bool_value=False)
        ... def first(items):
        ...     return items[:1]
        >>> first([1, 2])
        [1]
        >>> first([])
        Traceback (most recent call last):
        ValueError: empty
    """
    if always and (bool_value is not None or values is not None):
        msg = "raise_if: can't pass bool_value or values when always=True"
        raise ValueError(msg)

    if not always and bool_value is None and values is None:
        msg = "raise_if: pass bool_value, values or always=True, or nothing can ever raise"
        raise ValueError(msg)

    # `None` is a value to match like any other here, so the flattening keeps it.
    listed = (
        frozenset() if values is None else frozenset(iter_flat_cont(values, exclude_none=False))
    )

    def _matches(result: Any) -> bool:
        """Tell whether a result should raise.

        Args:
            result: The decorated function's result.

        Returns:
            Whether it matches the conditions.
        """
        try:
            is_listed = result in listed
        except TypeError:
            is_listed = False

        return always or is_listed or (bool_value is not None and bool(result) == bool_value)

    def _to_raise() -> BaseException:
        """Build the exception for one raise.

        Returns:
            A fresh one from the factory, or the shared instance with its traceback and context cleared.
        """
        if not isinstance(exc, BaseException):
            return exc()

        exc.__context__ = None
        return exc.with_traceback(None)

    def decorator(func: Callable[_P, Any]) -> Callable[_P, Any]:
        """Wrap `func`.

        Args:
            func: The function to watch.

        Returns:
            The wrapper.
        """
        if _is_async_callable(func):

            async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
                """Await `func` and raise on a matching result."""
                result = await call_sync_or_await(func, *args, **kwargs)

                if _matches(result):
                    raise _to_raise()

                return result
        else:

            def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
                """Call `func` and raise on a matching result."""
                result = func(*args, **kwargs)

                if _matches(result):
                    raise _to_raise()

                return result

        return functools.wraps(func)(wrapper)

    return decorator


__all__ = (
    "safe_call",
    "raise_if",
)
