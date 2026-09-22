from __future__ import annotations as _annotations

import asyncio
import sys

from typing import (
    Any, Awaitable,
    TypeAlias, Final,
    TYPE_CHECKING, overload
)
from .typings import MaybeAwaitableCallable, _True, _False, _T


_PY314: Final[bool] = sys.version_info >= (3, 14)

def _get_fut_loop(fut):
    try:
        get_loop = fut.get_loop
    except AttributeError:
        pass
    else:
        return get_loop()
    return fut._loop

def _get_running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return 


class _GatheringFuture(asyncio.Future):
    def __init__(self, children, *, loop):
        super().__init__(loop=loop)

        self._children = children

    if not TYPE_CHECKING:
        @property
        def cancel_message(self) -> Any | None:
            return getattr(self, "_cancel_message", None)
        
        @cancel_message.setter
        def cancel_message(self, value: Any | None):
            setattr(self, "_cancel_message", value)


        def cancel(self, msg: Any | None = None) -> bool:
            # Cancelling the outer future does not cancel *this* future
            # immediately -- it forwards the request to every child and lets
            # them unwind first, exactly like asyncio.gather(). _done_callback
            # only turns `outer` itself into a CancelledError once every child
            # has actually finished (npending == 0); until then `outer` stays
            # pending even though a cancellation is already in flight.
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
def _gather_cancel_on_error(*awaitables: Awaitable[_T], return_exceptions: _False = False) -> asyncio.Future[list[_T]]:...
@overload
def _gather_cancel_on_error(*awaitables: Awaitable[_T], return_exceptions: _True) -> asyncio.Future[list[_T | Exception]]:...
def _gather_cancel_on_error(*awaitables, return_exceptions = False):
    """Reimplementation of asyncio.gather() that cancels every sibling as soon
    as one fails (asyncio.gather() itself leaves the rest running).

    `_done_callback` fires once per child future and does one of three things:
      - if `outer` is already resolved (a prior sibling failed first, or the
        caller cancelled `outer` itself -- see _GatheringFuture.cancel above),
        the result/exception is only drained via fut.exception() so asyncio's
        "exception was never retrieved" warning doesn't fire on a future
        nobody will ever await again;
      - if this child failed and `return_exceptions` is False, `outer` is
        failed with that exception and every other still-running child is
        cancelled -- this is the actual "cancel on error" behavior;
      - once every child has reported in (`npending == 0`), results are
        collected in the original awaitables order and `outer` is resolved --
        as a success, or as CancelledError if `outer` was cancelled while
        children were still finishing (see _GatheringFuture.cancel, which
        lets already-running children finish instead of force-stopping them).

    `awaitable_2_fut` deduplicates: passing the same awaitable twice must not
    schedule it twice or count it twice toward `npending`, since asyncio.gather
    has the same behavior for repeated arguments.

    On 3.14+, `future_add_to_awaited_by`/`future_discard_from_awaited_by` keep
    each child's "awaited by" introspection link pointed at the *caller's*
    task instead of this function's internal bookkeeping -- otherwise tools
    like asyncio's task graph (or Task.print_stack()) would show the children
    as awaited by a frame that already returned.
    """

    if not awaitables:
        outer = asyncio.get_event_loop().create_future()
        outer.set_result([])
        return outer

    if _PY314:
        loop = _get_running_loop()
        current_task = None if loop is None else asyncio.current_task(loop)
    else:
        loop = None
        current_task = None
    

    def _done_callback(fut, current_task = current_task):
        nonlocal npending
        npending -= 1

        if _PY314 and current_task is not None:
            asyncio.future_discard_from_awaited_by(fut, current_task)

        if outer is None or outer.done():
            if not fut.cancelled():
                fut.exception()  # استهلاك الاستثناء لمنع تحذير asyncio
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
    
    
    
    npending = 0
    outer = None
    
    done_futs = []
    children = []

    awaitable_2_fut = {}
    

    for awaitable in awaitables:
        fut = awaitable_2_fut.get(awaitable)

        if fut is None:
            fut = asyncio.ensure_future(awaitable, loop=loop)

            if loop is None:
                loop = _get_fut_loop(fut)

            if fut is not awaitable:
                fut._log_destroy_pending = False

            npending += 1
            awaitable_2_fut[awaitable] = fut

            if fut.done():
                done_futs.append(fut)
            else:
                if _PY314 and current_task is not None:
                    asyncio.future_add_to_awaited_by(fut, current_task)

                fut.add_done_callback(_done_callback)

        children.append(fut)

    outer = _GatheringFuture(children, loop=loop)

    for fut in done_futs:
        _done_callback(fut)

    return outer



_ExcFilter: TypeAlias = type[BaseException] | tuple[type[BaseException], ...] | None
_ExcLogger: TypeAlias = bool | MaybeAwaitableCallable[[BaseException], Any]

_HARD_PROPAGATE: Final[tuple[type[SystemExit], type[KeyboardInterrupt]]] = (SystemExit, KeyboardInterrupt)
