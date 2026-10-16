"""Helpers private to `async_tools`: the cancel-on-error gather and error logging."""

from __future__ import annotations as _annotations

import asyncio
import logging
import sys
import traceback
from collections.abc import Awaitable
from typing import Any, Final, TypeAlias, overload

from .._internal._asyncio import _get_running_loop
from ..typings import MaybeAwaitableCallable, _False, _T, _True

_PY314: Final[bool] = sys.version_info >= (3, 14)
"""Whether the awaited-by introspection API of Python 3.14 is available."""

_ExcLogger: TypeAlias = bool | MaybeAwaitableCallable[[BaseException], Any]
"""`asafe_call`'s `log_exc`: `True` to log, or a sync or async callback receiving the exception."""

log = logging.getLogger(__name__)


class _GatheringFuture(asyncio.Future):
    """The future `_gather_cancel_on_error` returns; cancelling it cancels the children first.

    Like `asyncio.gather`, cancelling it forwards the request to every child
    and lets them unwind; it becomes cancelled only once they have finished.
    """

    def __init__(self, children: list[asyncio.Future[Any]], *, loop: asyncio.AbstractEventLoop | None) -> None:
        """Bind the future to its children.

        Args:
            children: The futures being gathered, in order.
            loop: The loop the future belongs to.
        """
        super().__init__(loop=loop)
        self._children = children

    @property
    def cancel_message(self) -> Any | None:
        """The message a cancellation was requested with, or `None` if none was."""
        return getattr(self, "_cancel_message", None)

    @cancel_message.setter
    def cancel_message(self, value: Any | None) -> None:
        """Record the cancellation message.

        Args:
            value: The message.
        """
        self._cancel_message = value

    def cancel(self, msg: Any | None = None) -> bool:
        """Ask every unfinished child to cancel.

        Args:
            msg: The cancellation message.

        Returns:
            Whether any child accepted the request.
        """
        if self.done():
            return False

        ret = False

        for child in self._children:
            if child.cancel(msg=msg):
                ret = True

        if ret:
            self.cancel_message = "" if msg is None else msg

        return ret


@overload
def _gather_cancel_on_error(*awaitables: Awaitable[_T], return_exceptions: _False = False) -> asyncio.Future[list[_T]]: ...
@overload
def _gather_cancel_on_error(
    *awaitables: Awaitable[_T], return_exceptions: _True,
) -> asyncio.Future[list[_T | Exception]]: ...
def _gather_cancel_on_error(*awaitables: Awaitable[Any], return_exceptions: bool = False) -> asyncio.Future[list[Any]]:
    """Gather like `asyncio.gather`, but cancel every sibling as soon as one fails.

    A repeated awaitable is scheduled and counted once. On 3.14 each child's
    awaited-by link points at the caller's task, so task-graph tools stay right.

    Args:
        *awaitables: The awaitables to run concurrently.
        return_exceptions: Whether failures are returned in place instead of
            failing the whole gather and cancelling the rest.

    Returns:
        A future resolving to the results in the original order.
    """
    if not awaitables:
        outer = asyncio.get_running_loop().create_future()
        outer.set_result([])
        return outer

    loop = _get_running_loop() if _PY314 else None
    current_task = asyncio.current_task(loop) if _PY314 and loop is not None else None
    npending = 0
    outer: _GatheringFuture | None = None
    done_futs: list[asyncio.Future[Any]] = []
    children: list[asyncio.Future[Any]] = []
    awaitable_2_fut: dict[Awaitable[Any], asyncio.Future[Any]] = {}

    def _done_callback(fut: asyncio.Future[Any]) -> None:
        """Account for one finished child, failing or resolving `outer` as needed.

        Args:
            fut: The child that finished.
        """
        nonlocal npending
        npending -= 1

        # The literal `sys.version_info` check, not `_PY314`, lets `ty` see the 3.14-only API.
        if sys.version_info >= (3, 14) and current_task is not None:
            asyncio.future_discard_from_awaited_by(fut, current_task)

        if outer is None or outer.done():
            if not fut.cancelled():
                fut.exception()  # Retrieve it, so asyncio does not warn it was never retrieved.
            return

        if not return_exceptions:
            try:
                exc = fut.exception()
            except asyncio.CancelledError as e:
                exc = e

            if exc is not None:
                outer.set_exception(exc)

                for child in children:
                    if child is not fut and not child.done():
                        child.cancel()

                return

        if npending == 0:
            results = []

            for child in children:
                try:
                    result = child.exception()
                except asyncio.CancelledError as e:
                    result = e

                if result is None:
                    try:
                        result = child.result()
                    except (Exception, asyncio.CancelledError) as e:
                        result = e

                results.append(result)

            if (cancel_message := outer.cancel_message) is not None:
                outer.set_exception(asyncio.CancelledError(cancel_message))
            else:
                outer.set_result(results)

    for awaitable in awaitables:
        fut = awaitable_2_fut.get(awaitable)

        if fut is None:
            fut = asyncio.ensure_future(awaitable, loop=loop)

            if loop is None:
                loop = _get_fut_loop(fut)

            if fut is not awaitable:
                # Silences "Task was destroyed but it is pending", as `asyncio.gather` does; the
                # private `Task._log_destroy_pending` is missing from typeshed, hence `setattr`.
                setattr(fut, "_log_destroy_pending", False)

            npending += 1
            awaitable_2_fut[awaitable] = fut

            if fut.done():
                done_futs.append(fut)
            else:
                # The literal `sys.version_info` check, not `_PY314`, lets `ty` see the 3.14-only API.
                if sys.version_info >= (3, 14) and current_task is not None:
                    asyncio.future_add_to_awaited_by(fut, current_task)

                fut.add_done_callback(_done_callback)

        children.append(fut)

    outer = _GatheringFuture(children, loop=loop)

    for fut in done_futs:
        _done_callback(fut)

    return outer


def _get_fut_loop(fut: asyncio.Future[Any]) -> asyncio.AbstractEventLoop:
    """Return the loop a future belongs to, even for one without `get_loop`.

    Args:
        fut: The future.

    Returns:
        Its event loop.
    """
    try:
        get_loop = fut.get_loop
    except AttributeError:
        return fut._loop

    return get_loop()


def _log_exc(
    header: str | None,
    caller_stack: list[traceback.FrameSummary] | None,
    exc: BaseException,
    index: int | None = None,
) -> None:
    """Log an exception with the caller's stack above its own traceback.

    Args:
        header: The first line of the message.
        caller_stack: Where the async helper was called from.
        exc: The exception.
        index: The awaitable's position, for helpers that run several.
    """
    exc_trace = traceback.format_exception(type(exc), exc, exc.__traceback__)
    caller_trace = traceback.format_list(caller_stack or [])
    header = header or ""

    if index is not None:
        header = f"{header} [awaitable index={index}]" if header else f"[awaitable index={index}]"

    log.error("%s\n%s", header, "".join(caller_trace) + "".join(exc_trace))


__all__ = (
    "_GatheringFuture",
    "_gather_cancel_on_error",
    "_get_fut_loop",
    "_log_exc",
    "_ExcLogger",
    "_PY314",
)
