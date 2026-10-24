"""A private event loop on its own thread, for running coroutines from anywhere."""

from __future__ import annotations as _annotations

import asyncio
import sys
import threading
from typing import TYPE_CHECKING, Any

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from ._internal import _LoopHost, _run_tracked
from .run import to_thread

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator

    from ..typings import Number, _P, _T


class AioThreadWorker(_LoopHost):
    """Runs coroutine functions on a private event loop in its own thread.

    `submit` is awaitable from any thread or loop; cancelling the await
    cancels the work too. A worker owns one thread for its whole life.
    `concurrency` caps simultaneous submissions (0 or less: no cap); under a
    cap, work must not await `submit` on the same worker or it deadlocks.
    Only lifecycle transitions take the lock: state only moves one way, the
    loop is published before "running" is set, and `submit` re-validates
    through `get_loop` right before scheduling. A submission that loses the
    race with `join` raises `RuntimeError`, never hangs.

    Example:
        >>> async def main():
        ...     async with AioThreadWorker() as worker:
        ...         return await worker.submit(asyncio.sleep, 0, result=1)
        >>> asyncio.run(main())
        1
    """

    async def join(self, timeout: Number | None = None) -> None:
        """Stop the worker: refuse new work, let in-flight work finish, wait for the thread.

        Safe to call repeatedly and concurrently; on a never-started worker it
        still prevents any future start.

        Args:
            timeout: Seconds for the final wait on the thread only.

        Raises:
            RuntimeError: If called from the worker's own thread.
            TimeoutError: If the thread is still alive after `timeout`.
        """
        if threading.current_thread() is self._thread:
            msg = "cannot join from inside the worker's own thread -- waiting for it to drain would deadlock"
            raise RuntimeError(msg)

        with self._lock:
            was_stopping = self._stopping
            self._stopping = True

        thread = self._thread

        if thread is None:
            return

        if not was_stopping:
            await to_thread(self.wait_for_running)
            loop = self._loop
            drain = self._drain

            # `_bootstrap` clears `_loop` and `_drain` only after the drain set below, so both
            # are published here; the check only narrows their `| None` for the checker.
            if loop is not None and drain is not None:
                loop.call_soon_threadsafe(drain.set)  # `asyncio.Event` is not thread-safe.

        if not thread.is_alive():
            return

        await to_thread(thread.join, timeout)

        if timeout is not None and thread.is_alive():
            msg = f"worker did not stop within {timeout!r} seconds"
            raise TimeoutError(msg)

    def __await__(self) -> Generator[Any, None, None]:
        """Await the worker to `join` it."""
        return self.join().__await__()

    async def submit(
        self, func: Callable[_P, Awaitable[_T]], /, *args: _P.args, **kwargs: _P.kwargs
    ) -> _T:
        """Call `func(*args, **kwargs)` on the worker's loop and await its result.

        Args:
            func: An awaitable function, called on the worker's loop.
            *args: Its positional arguments.
            **kwargs: Its keyword arguments.

        Returns:
            Its result.

        Raises:
            RuntimeError: If the worker is not running, is stopping, or stops
                before the work completes.
            TypeError: If `func` does not return an awaitable.
        """
        if not self.is_running():
            msg = "worker is closed"
            raise RuntimeError(msg)

        if self.is_stopping():
            msg = "worker is stopping"
            raise RuntimeError(msg)

        try:
            loop = self.get_loop()  # The authoritative check, right before the hand-off.
            work = _run_tracked(func, args, kwargs, self._tasks, self._slots)

            if asyncio.get_running_loop() == loop:
                return await work

            return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(work, loop))
        except asyncio.CancelledError:
            cancelling = getattr(asyncio.current_task(), "cancelling", None)

            if (
                cancelling is not None
                and cancelling() == 0
                and (self.is_stopping() or not self.is_running())
            ):
                msg = "AioThreadWorker stopped before this task completed"
                raise RuntimeError(msg) from None

            raise

    __call__ = submit

    async def __aenter__(self) -> Self:
        """Start the worker and wait until it runs.

        Returns:
            The worker.
        """
        self.run()
        self.wait_for_running()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Join the worker.

        Args:
            *exc_info: The exception, if any; not suppressed.
        """
        await self.join()


__all__ = ("AioThreadWorker",)
