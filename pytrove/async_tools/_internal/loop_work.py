"""What exists only while a private event loop runs: the loop, its tracked tasks, its cap, its drain.

This module knows `asyncio` only, never `threading`. A `_LoopWork` is built on
the loop's own thread once the loop runs, so none of its fields is ever `None`,
and every method but `schedule` and `request_drain` runs on that loop.
"""

from __future__ import annotations as _annotations

import asyncio
import concurrent.futures
import contextlib
import inspect
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

    from ...typings import _T


class _LoopWork:
    """Track the submissions on one running loop, cap how many run at once, and drain them on request."""

    def __init__(self, loop: asyncio.AbstractEventLoop, concurrency: int) -> None:
        """Set the loop's state up; built on the loop's own thread.

        Args:
            loop: The running loop this work lives on.
            concurrency: The most submissions running at once; 0 or less for no cap.
        """
        self.loop = loop
        """The running loop; other threads reach it only to schedule on it."""

        self.tasks: set[asyncio.Task[Any]] = set()
        """The tasks the drain waits for; touched only on the loop."""

        self.slots = asyncio.Semaphore(concurrency) if concurrency > 0 else None
        """The concurrency cap, or `None` for none; touched only on the loop."""

        self.drain = asyncio.Event()
        """Set once to start the drain; set only on the loop, through `request_drain`."""

        self.closed = False
        """Set once the drain starts, or the loop's main coroutine ends; touched only on the loop.

        From then on `schedule` creates no task, and a task whose first step comes
        later is refused before it is tracked or `func` is called: the drain waits
        only for what had already started.
        """

    async def run(
        self, func: Callable[..., Awaitable[_T]], args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> _T:
        """Run one submission, tracked for the drain and bounded by the cap.

        Runs on: the loop, inside the submission's task.

        The task registers before waiting for a slot, so a drain sees it even
        while parked, and `func` is called only once a slot is held, so a
        submission cancelled while parked leaves no coroutine behind. A nested
        submission runs inline in a task that is already tracked, inside the slot
        that task holds: only the call that registered the task takes a slot and
        removes the task again.

        Args:
            func: The awaitable function.
            args: Its positional arguments.
            kwargs: Its keyword arguments.

        Returns:
            The result.

        Raises:
            TypeError: If calling `func` does not give an awaitable.
            asyncio.CancelledError: If the loop is already closed to work; the caller sees its
                usual "stopped before this task completed".
        """
        if self.closed:
            raise asyncio.CancelledError

        task = asyncio.current_task()
        added = False

        # Always a task in practice (`submit` awaits it in one, `_schedule` makes it one); the
        # check only narrows `current_task`'s `Task | None` for the set.
        if task is not None and task not in self.tasks:
            self.tasks.add(task)  # Before the first `await`, so a drain already running sees it.
            added = True

        # A nested call runs inside the slot its tracked task already holds; a second
        # acquire would deadlock once every slot is held by a task nesting like this.
        slots = self.slots if added else None

        try:
            if slots is not None:
                await slots.acquire()

            try:
                awaitable = func(*args, **kwargs)

                if not inspect.isawaitable(awaitable):
                    msg = f"func must be an awaitable function; calling it returned {type(awaitable).__name__!r}"
                    raise TypeError(msg)

                return await awaitable
            finally:
                if slots is not None:
                    slots.release()  # Synchronous, so a cancellation cannot leak the slot.
        finally:
            if added:
                self.tasks.discard(task)

    def schedule(self, coro: Coroutine[Any, Any, _T]) -> concurrent.futures.Future[_T]:
        """Run `coro` as a task on the loop, from another thread, unless the work closes first.

        Runs on: any thread. Like `asyncio.run_coroutine_threadsafe`, and it wakes the
        loop the same way, but the task is created on the loop only while the work is
        open: once `closed` is set none is made, so no task is ever left unstepped
        when the loop closes (its cancellation would then hit the closed loop).

        Args:
            coro: The coroutine to run.

        Returns:
            The future of its outcome; cancelled if the work closed before it started.

        Raises:
            RuntimeError: If the loop is already closed.
        """
        fut: concurrent.futures.Future[_T] = concurrent.futures.Future()

        def start() -> None:
            """Create the task, or refuse it; on the loop."""
            if self.closed or fut.cancelled():
                coro.close()
                fut.cancel()
                return

            task = self.loop.create_task(coro)

            def settle(done: asyncio.Task[_T]) -> None:
                """Copy the task's outcome to the future; on the loop."""
                if done.cancelled():
                    fut.cancel()
                elif fut.set_running_or_notify_cancel():  # `False`: the caller cancelled it.
                    exc = done.exception()

                    if exc is None:
                        fut.set_result(done.result())
                    else:
                        fut.set_exception(exc)

            def forward_cancel(done: concurrent.futures.Future[_T]) -> None:
                """Cancel the task once the caller cancelled the future; on the caller's thread."""
                if done.cancelled():
                    with contextlib.suppress(RuntimeError):  # The loop closed meanwhile.
                        self.loop.call_soon_threadsafe(task.cancel)

            task.add_done_callback(settle)
            fut.add_done_callback(forward_cancel)

        self.loop.call_soon_threadsafe(start)
        return fut

    async def wait_drained(self) -> None:
        """Sleep until a drain is requested, then close the work and wait for every tracked task.

        Runs on: the loop; the loop's main coroutine awaits it last.
        """
        await self.drain.wait()
        # Nothing registers from now on (`run` refuses), so one gather waits for all of it.
        self.closed = True
        await asyncio.gather(*self.tasks, return_exceptions=True)

    def request_drain(self) -> None:
        """Ask the loop to start draining.

        Runs on: any thread; the only method here that may.

        Raises:
            RuntimeError: If the loop is already closed.
        """
        self.loop.call_soon_threadsafe(self.drain.set)  # `asyncio.Event` is not thread-safe.


__all__ = ("_LoopWork",)
