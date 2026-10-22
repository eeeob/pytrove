"""A persistent event loop on a background thread, for running awaitables from sync code."""

from __future__ import annotations as _annotations

import asyncio
import sys
import threading
from typing import TYPE_CHECKING

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from ._threads import _check_loop_factory, _run_loop
from .run import run_awaitable_in_coro

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ..typings import _T


class SyncAwaitableRunner:
    """Keeps one event loop alive on a background thread and runs awaitables on it from sync code.

    Unlike `run_awaitable_sync`, which builds a loop per call, state bound to
    the loop survives between `run` calls. `close` lets the loop drain every
    task before it is torn down; a submission that loses that race raises
    `RuntimeError` instead of hanging.

    Example:
        >>> import asyncio
        >>> with SyncAwaitableRunner() as runner:
        ...     runner.run(asyncio.sleep(0, result=1))
        1
    """

    def __init__(
        self,
        name: str | None = None,
        lazy: bool = False,
        loop_factory: Callable[[], asyncio.AbstractEventLoop] | None = None,
    ) -> None:
        """Configure the runner, and start it unless `lazy`.

        Args:
            name: The thread's name.
            lazy: Whether to wait for the first `run` before starting.
            loop_factory: Builds the loop (Python 3.12+; ignored with a warning before).

        Raises:
            TypeError: If `loop_factory` is not callable.
        """
        _check_loop_factory(loop_factory)

        self.__name = name
        self.__loop_factory = loop_factory
        self.__lock = threading.RLock()
        self.__thread: threading.Thread | None = None
        self.__loop: asyncio.AbstractEventLoop | None = None
        self.__stopping: asyncio.Event | None = None
        self.__closed = False

        if not lazy:
            self.start()

    @property
    def started(self) -> bool:
        """Whether the thread was ever started; never goes back."""
        return self.__thread is not None

    @property
    def running(self) -> bool:
        """Whether the loop is up and accepting work (not starting, not draining)."""
        thread = self.__thread
        stopping = self.__stopping
        return thread is not None and thread.is_alive() and stopping is not None and not stopping.is_set()

    @property
    def closed(self) -> bool:
        """Whether `close` has been called; never goes back."""
        return self.__closed

    def start(self) -> None:
        """Start the background thread and block until its loop is ready or has failed.

        Raises:
            RuntimeError: If it is already started or closed.
        """
        started = threading.Event()

        async def _worker() -> None:
            """Publish the loop, wait for `close`, then drain every other task on it."""
            self.__stopping = stopping = asyncio.Event()
            self.__loop = loop = asyncio.get_running_loop()
            started.set()
            await stopping.wait()
            current_task = asyncio.current_task(loop)

            # A fresh list each pass: a task created during an earlier gather is caught by the next.
            while tasks := [t for t in asyncio.all_tasks(loop=loop) if t is not current_task]:
                await asyncio.gather(*tasks, return_exceptions=True)

        def _bootstrap() -> None:
            """Run the loop for the thread's whole life."""
            loop_factory = self.__loop_factory
            del self.__loop_factory

            try:
                _run_loop(_worker(), loop_factory)
            finally:
                self.__loop = None
                self.__stopping = None
                started.set()  # Releases `start` even when the loop failed before publishing.

        from ..callable_tools import safe_call  # noqa: PLC0415 - `callable_tools` imports `async_tools`

        with self.__lock:
            if self.started:
                msg = f"{self.__class__.__name__} is already started"
                raise RuntimeError(msg)

            if self.__closed:
                msg = f"{self.__class__.__name__} is closed"
                raise RuntimeError(msg)

            thread = threading.Thread(
                target=safe_call, args=(_bootstrap,), kwargs={"log_exc": True}, name=self.__name, daemon=True,
            )
            del self.__name
            thread.start()
            started.wait()
            self.__thread = thread

    def run(self, awaitable: Awaitable[_T]) -> _T:
        """Run an awaitable on the loop and block until it completes, starting the loop if needed.

        Args:
            awaitable: The awaitable.

        Returns:
            Its result.

        Raises:
            RuntimeError: If the runner is closed or its loop is not running.
        """
        if not self.started:
            try:
                self.start()
            except RuntimeError:
                if self.closed:  # Losing a start race is fine; being closed is not.
                    raise

        loop = self.__loop

        if not self.running or loop is None:
            msg = f"{self.__class__.__name__} is not running"
            raise RuntimeError(msg)

        coro = awaitable if asyncio.iscoroutine(awaitable) else run_awaitable_in_coro(awaitable)

        try:
            fut = asyncio.run_coroutine_threadsafe(coro, loop)
        except AttributeError:
            msg = f"{self.__class__.__name__}'s event loop disappeared while scheduling"
            raise RuntimeError(msg) from None

        if not loop.is_running():
            msg = f"{self.__class__.__name__}'s event loop is no longer running"
            raise RuntimeError(msg)

        return fut.result()

    __call__ = run

    def close(self) -> None:
        """Stop the loop after it drains, and wait for the thread; safe to repeat.

        Raises:
            RuntimeError: If called from the runner's own thread.
        """
        if self.__thread is not None and threading.current_thread() is self.__thread:
            msg = "cannot close from inside the runner's own thread -- waiting for it would deadlock"
            raise RuntimeError(msg)

        with self.__lock:
            if self.__closed:
                return

            self.__closed = True

        thread = self.__thread
        loop = self.__loop
        stopping = self.__stopping

        if thread is None or loop is None or stopping is None:
            return

        loop.call_soon_threadsafe(stopping.set)  # `asyncio.Event` is not thread-safe.
        thread.join()

    def __enter__(self) -> Self:
        """Use the runner as a context manager.

        Returns:
            The runner.
        """
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close the runner.

        Args:
            *exc_info: The exception, if any; not suppressed.
        """
        self.close()


__all__ = ("SyncAwaitableRunner",)
