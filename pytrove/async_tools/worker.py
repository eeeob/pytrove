"""A private event loop on its own thread, for running coroutines from anywhere."""

from __future__ import annotations as _annotations

import asyncio
import sys
from functools import cached_property
from typing import TYPE_CHECKING, Any, cast

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from ..object_tools.proxies import WeakRestrictedProxy
from ._internal import _LoopHost
from .run import to_thread

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator

    from ..typings import Number, _P, _T


class AioThreadWorker(_LoopHost):
    """Runs coroutine functions on a private event loop in its own thread.

    `submit` is awaitable from any thread or loop; cancelling the await
    cancels the work too. A worker owns one thread for its whole life and
    starts it once: a second `run` raises. `concurrency` caps simultaneous
    submissions (0 or less: no cap); a `submit` awaited from work already on the
    worker runs inside that work's slot. `submit` is lock-free, so any number of
    threads submit at once; only lifecycle moves (`run`, `join`, the start and
    end of the loop) take the lock. `join` drains the work that had started on
    the loop when it began; work that had not started yet is dropped, and
    its caller gets `RuntimeError`, never a hang. If the thread dies, `join`
    returns what killed it; nothing is logged. Only `get_loop` needs the
    `proxy` extra.

    Example:
        >>> async def main():
        ...     async with AioThreadWorker() as worker:
        ...         return await worker.submit(asyncio.sleep, 0, result=1)
        >>> asyncio.run(main())
        1
    """

    @cached_property
    def _loop_proxy(self) -> asyncio.AbstractEventLoop:
        """The loop handed to callers, with `close` and `stop` denied so its lifecycle stays the worker's.

        From 3.12 `cached_property` takes no lock, so two first calls racing may each
        build a proxy; both wrap the same loop, and one of them is kept.

        Raises:
            RuntimeError: If the loop is not published yet.
        """
        work = self._state().work

        if work is None:
            msg = "the worker's event loop has not been published yet -- use get_loop(), which checks that"
            raise RuntimeError(msg)

        # The proxy forwards every loop method but the two it blocks; `ty` sees only the proxy type.
        return cast(
            "asyncio.AbstractEventLoop", WeakRestrictedProxy(work.loop, blocked=["close", "stop"])
        )

    def get_loop(self) -> asyncio.AbstractEventLoop:
        """Return the worker's loop, unable to be stopped or closed from outside.

        Returns:
            A proxy of the loop.

        Raises:
            RuntimeError: If the worker or its loop is not running, or the loop is closed.
            ImportError: Without the `proxy` extra.
        """
        self._checked_work(new_work=False)  # A draining loop is still handed out.
        return self._loop_proxy

    async def join(self, timeout: Number | None = None) -> BaseException | None:
        """Stop the worker: refuse new work, let in-flight work finish, wait for the thread.

        Safe to call repeatedly and concurrently, and after the thread died; on
        a never-started worker it still prevents any future start.

        Args:
            timeout: Seconds for the final wait on the thread only.

        Returns:
            What ended the thread or failed to start it, the same every time; `None`
            after a clean stop or for a worker never started. It is never raised.

        Raises:
            RuntimeError: If called from the worker's own thread.
            TimeoutError: If the thread is still alive after `timeout`.
        """
        if self._on_own_thread():
            msg = "cannot join from inside the worker's own thread -- waiting for it to drain would deadlock"
            raise RuntimeError(msg)

        return await to_thread(self._stop, timeout, log_exc=False)

    def __await__(self) -> Generator[Any, None, BaseException | None]:
        """Await the worker to `join` it; gives what `join` returns."""
        return self.join().__await__()

    async def submit(
        self, func: Callable[_P, Awaitable[_T]], /, *args: _P.args, **kwargs: _P.kwargs
    ) -> _T:
        """Call `func(*args, **kwargs)` on the worker's loop and await its result.

        From the worker's own loop the call runs inline, in the calling task.

        Args:
            func: An awaitable function, called on the worker's loop.
            *args: Its positional arguments.
            **kwargs: Its keyword arguments.

        Returns:
            Its result.

        Raises:
            RuntimeError: If the worker is not started, not running yet, closed or
                stopping, or stops before the work completes.
            TypeError: If `func` does not return an awaitable.
        """
        if self._on_own_loop():  # Already in a tracked task on the loop: run inline, no hop.
            return await self._checked_work().run(func, args, kwargs)

        fut = asyncio.wrap_future(self._schedule(func, args, kwargs))

        try:
            # Shielded, so a cancellation of the caller stays apart from one of the work.
            return await asyncio.shield(fut)
        except asyncio.CancelledError:
            if not fut.done():  # The caller was cancelled: cancel the work too.
                fut.cancel()
                raise

            # The stop can cancel the work, and the caller be cancelled before it wakes:
            # that request is the caller's own, so on 3.11+ it stays a cancellation.
            task = asyncio.current_task()

            if sys.version_info >= (3, 11) and task is not None and task.cancelling():
                raise

            if fut.cancelled() and self._state().gone:
                msg = "AioThreadWorker stopped before this task completed"
                raise RuntimeError(msg) from None

            raise

    __call__ = submit

    async def __aenter__(self) -> Self:
        """Start the worker unless `run_now` already did, and wait, off the calling loop, until it runs.

        Returns:
            The worker.

        Raises:
            RuntimeError: If the worker was stopped, has finished, or its thread died starting.
        """
        self._ensure_started()  # Not `run`: it starts only once, and `run_now` may have used it.
        await to_thread(self.wait_for_running, log_exc=False)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Join the worker; what ended its thread is not raised (call `join` to get it).

        Args:
            *exc_info: The exception, if any; not suppressed.
        """
        await self.join()


__all__ = ("AioThreadWorker",)
