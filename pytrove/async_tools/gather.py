"""Running many awaitables concurrently."""

from __future__ import annotations as _annotations

import asyncio
import traceback
from collections.abc import Awaitable, Iterator
from typing import TYPE_CHECKING, Any, cast, overload

from ..iter_tools import iter_flat_cont
from ..validate_tools import is_exception
from ._internal import _gather_cancel_on_error, _log_exc

if TYPE_CHECKING:
    from ..typings import NestedContainer, _False, _T


# `return_exc=False` (or nothing) is listed first, so `True` or a plain `bool` falls to the arm
# that may return an exception.
@overload
async def gather_helper(
    *awaitables: NestedContainer[Awaitable[_T] | None],
    return_exc: _False = False,
    log_exc: bool = True,
) -> list[_T]: ...
@overload
async def gather_helper(
    *awaitables: NestedContainer[Awaitable[_T] | None],
    return_exc: bool,
    log_exc: bool = True,
) -> list[_T | Exception | asyncio.CancelledError]: ...
async def gather_helper(
    *awaitables: Any, return_exc: bool = False, log_exc: bool = True
) -> list[Any]:
    """Run awaitables concurrently like `asyncio.gather`, flattening nested containers.

    `None` entries are skipped.

    Args:
        *awaitables: Awaitables, or containers of them, at any depth.
        return_exc: Whether failures are returned in place; otherwise the first one is raised.
        log_exc: Whether to log each returned failure with the caller's stack.

    Returns:
        The results in order.

    Example:
        >>> asyncio.run(gather_helper(asyncio.sleep(0, result=1), [asyncio.sleep(0, result=2), None]))
        [1, 2]
    """
    caller_stack = traceback.extract_stack()[:-1] if log_exc else None
    # `ty` binds `_T` to the container arm of the recursive `NestedContainer[_T]`, so
    # it cannot recover the leaf type (astral-sh/ty#1703); the parameter states it.
    leaves = cast(Iterator[Awaitable[Any]], iter_flat_cont(awaitables))
    results = await asyncio.gather(*leaves, return_exceptions=return_exc)

    if log_exc and return_exc:
        for i, r in enumerate(results):
            if is_exception(r):
                _log_exc("error in gather_helper", caller_stack, r, index=i)

    return results


# Same overload order as `gather_helper`.
@overload
async def gather_abort(
    *awaitables: NestedContainer[Awaitable[_T] | None],
    return_exc: _False = False,
    log_exc: bool = True,
) -> list[_T]: ...
@overload
async def gather_abort(
    *awaitables: NestedContainer[Awaitable[_T] | None],
    return_exc: bool,
    log_exc: bool = True,
) -> list[_T | Exception | asyncio.CancelledError]: ...
async def gather_abort(
    *awaitables: Any, return_exc: bool = False, log_exc: bool = True
) -> list[Any]:
    """Run awaitables concurrently, cancelling the rest as soon as one fails.

    Args:
        *awaitables: Awaitables, or containers of them, at any depth.
        return_exc: Whether failures are returned in place, without cancelling.
        log_exc: Whether to log each returned failure with the caller's stack.

    Returns:
        The results in order.
    """
    caller_stack = traceback.extract_stack()[:-1] if log_exc else None
    # `ty` binds `_T` to the container arm of the recursive `NestedContainer[_T]`, so
    # it cannot recover the leaf type (astral-sh/ty#1703); the parameter states it.
    leaves = cast(Iterator[Awaitable[Any]], iter_flat_cont(awaitables))
    results = await _gather_cancel_on_error(*leaves, return_exceptions=return_exc)

    if log_exc and return_exc:
        for i, r in enumerate(results):
            if is_exception(r):
                _log_exc("error in gather_abort", caller_stack, r, index=i)

    return results


__all__ = (
    "gather_helper",
    "gather_abort",
)
