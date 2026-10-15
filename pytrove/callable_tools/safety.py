"""Calling with exceptions swallowed, and raising on chosen results."""

from __future__ import annotations as _annotations

import functools
import logging
from collections.abc import Callable, Hashable
from typing import Any, overload

from .._internal._exceptions import _HARD_PROPAGATE
from .._internal._types import _ExcFilter
from ..iter_tools import iter_flat_cont, to_frozenset
from ..typings import NestedContainer, _ExcT, _False, _P, _T, _True
from ..validate_tools import iscoroutinefunction_wrapped
from ._internal import _ExcLogger

log = logging.getLogger(__name__)


@overload
def safe_call(
    func: Callable[_P, _T], *args: _P.args, include_exc: _ExcFilter = None, exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False, **kwargs: _P.kwargs,
) -> _T | None: ...
@overload
def safe_call(
    func: Callable[_P, _T], *args: _P.args, return_exc: _False, include_exc: _ExcFilter = None,
    exclude_exc: _ExcFilter = None, log_exc: _ExcLogger = False, **kwargs: _P.kwargs,
) -> _T | None: ...
@overload
def safe_call(
    func: Callable[_P, _T], *args: _P.args, return_exc: _True, include_exc: type[_ExcT],
    exclude_exc: _ExcFilter = None, log_exc: _ExcLogger = False, **kwargs: _P.kwargs,
) -> _T | _ExcT: ...
@overload
def safe_call(
    func: Callable[_P, _T], *args: _P.args, return_exc: _True, include_exc: tuple[type[_ExcT], ...],
    exclude_exc: _ExcFilter = None, log_exc: _ExcLogger = False, **kwargs: _P.kwargs,
) -> _T | _ExcT: ...
@overload
def safe_call(
    func: Callable[_P, _T], *args: _P.args, return_exc: _True, include_exc: _ExcFilter = None,
    exclude_exc: _ExcFilter = None, log_exc: _ExcLogger = False, **kwargs: _P.kwargs,
) -> _T | BaseException: ...
@overload
def safe_call(
    func: Callable[_P, _T], *args: _P.args, raise_exc: _True, include_exc: _ExcFilter = None,
    exclude_exc: _ExcFilter = None, log_exc: _ExcLogger = False, **kwargs: _P.kwargs,
) -> _T: ...
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
        TypeError: If `return_exc` and `raise_exc` are both set, or `exclude_exc`
            names an exception that always propagates anyway.
        BaseException: Whatever is not swallowed, or anything when `raise_exc` is set.
    """
    if return_exc and raise_exc:
        msg = "safe_call: return_exc and raise_exc cannot both be True -- raise_exc means the exception is never returned, only re-raised"
        raise TypeError(msg)

    if exclude_exc is not None:
        for exc_type in exclude_exc if isinstance(exclude_exc, tuple) else (exclude_exc,):
            if issubclass(exc_type, _HARD_PROPAGATE):
                msg = f"exclude_exc: {exc_type.__name__} always propagates already -- no need to list it"
                raise TypeError(msg)

    try:
        return func(*args, **kwargs)
    except _HARD_PROPAGATE:
        raise
    except BaseException as e:
        if exclude_exc is not None and isinstance(e, exclude_exc):
            raise

        if include_exc is not None and not isinstance(e, include_exc):
            raise

        if log_exc:
            if callable(log_exc):
                log_exc(e)
            else:
                log.error("error in safe_call(%r)", func, exc_info=e)

        if raise_exc:
            raise

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
    its truth value equals `bool_value`. An unhashable result never matches `values`.

    Args:
        exc: The exception to raise, or a factory building a fresh one each time.
        bool_value: The truth value that raises; `None` to ignore truthiness.
        values: The results that raise.
        always: Whether every result raises.

    Returns:
        The decorator.

    Raises:
        ValueError: If `always` is combined with `bool_value` or `values`.
    """
    if always and (bool_value is not None or values is not None):
        msg = "raise_if: can't pass bool_value or values when always=True"
        raise ValueError(msg)

    listed = to_frozenset(iter_flat_cont(values))

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

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap `func`.

        Args:
            func: The function to watch.

        Returns:
            The wrapper.
        """
        if iscoroutinefunction_wrapped(func):

            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                """Await `func` and raise on a matching result."""
                result = await func(*args, **kwargs)

                if _matches(result):
                    raise exc() if callable(exc) else exc

                return result

            return functools.wraps(func)(async_wrapper)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Call `func` and raise on a matching result."""
            result = func(*args, **kwargs)

            if _matches(result):
                raise exc() if callable(exc) else exc

            return result

        return functools.wraps(func)(wrapper)

    return decorator


__all__ = (
    "safe_call",
    "raise_if",
)
