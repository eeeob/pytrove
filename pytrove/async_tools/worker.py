"""A private event loop on its own thread, for running coroutines from anywhere."""

from __future__ import annotations as _annotations

import asyncio
import logging
import sys
import threading
import time
from collections.abc import Awaitable, Callable, Generator
from functools import cached_property, partial
from typing import Any

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from ..typings import Number, _P, _T
from ._threads import _check_loop_factory, _run_loop, _run_tracked
from .run import to_thread

log = logging.getLogger(__name__)


class AioThreadWorker:
    """Runs coroutine functions on a private event loop in its own thread.

    `submit` is awaitable from any thread or loop; cancelling the await
    cancels the work too. A worker owns one thread for its whole life.
    `concurrency` caps simultaneous submissions (0 or less: no cap); under a
    cap, work must not await `submit` on the same worker or it deadlocks.
    Only lifecycle transitions take the lock: state only moves one way, the
    loop is published before "running" is set, and `submit` re-validates
    through `get_loop` right before scheduling. A submission that loses the
    race with `join` raises `RuntimeError`, never hangs.
    """

    def __init__(
        self,
        name: str | None = None,
        concurrency: int = 0,
        loop_factory: Callable[[], asyncio.AbstractEventLoop] | None = None,
        exception_handler: Callable[[asyncio.AbstractEventLoop, dict[str, Any]], Any] | None = None,
        run_now: bool = True,
    ) -> None:
        """Configure the worker, and start it unless `run_now` is false.

        Args:
            name: The thread's name.
            concurrency: The most submissions running at once; 0 or less for no cap.
            loop_factory: Builds the loop (Python 3.12+; ignored with a warning before).
            exception_handler: Installed on the loop.
            run_now: Whether to start the thread now.

        Raises:
            TypeError: For a non-int `concurrency` or a non-callable factory or handler.
        """
        if not isinstance(concurrency, int):  # A bool passes on purpose: `True` reads as a cap of 1.
            msg = f"concurrency must be an int, got {type(concurrency).__name__!r}"
            raise TypeError(msg)

        if exception_handler is not None and not callable(exception_handler):
            msg = f"exception_handler must be callable, got {type(exception_handler).__name__!r}"
            raise TypeError(msg)

        _check_loop_factory(loop_factory)

        self.__name = name
        self.__concurrency = concurrency
        self.__loop_factory = loop_factory
        self.__exception_handler = exception_handler
        self.__lock = threading.RLock()
        self.__running = threading.Event()
        self.__thread: threading.Thread | None = None
        self.__thread_ready = threading.Event()
        self.__loop: asyncio.AbstractEventLoop | None = None
        self.__tasks: set[asyncio.Task[Any]] | None = None
        self.__slots: asyncio.Semaphore | None = None
        self.__drain: asyncio.Event | None = None
        self.__stopping = False
        self.__thread_exc: BaseException | None = None

        if run_now:
            self.run()

    @cached_property
    def __loop_proxy(self) -> Any:
        """The loop handed to callers, with `close` and `stop` denied so its lifecycle stays the worker's.

        Raises:
            RuntimeError: If the loop is not published yet.
        """
        if self.__loop is None:
            msg = "the worker's event loop has not been published yet -- use get_loop(), which waits on that"
            raise RuntimeError(msg)

        from ..object_tools.proxies import WeakRestrictedProxy  # `object_tools` sits above `async_tools`.

        return WeakRestrictedProxy(self.__loop, blocked=["close", "stop"])

    def __bootstrap(self) -> None:
        """Run the loop for the worker's whole life, on the worker thread.

        Raises:
            RuntimeError: If called from any other thread.
        """
        self.__thread_ready.wait()  # `run` publishes `__thread` only after starting it.

        if threading.current_thread() is not self.__thread:
            msg = "Bootstrap must be called from the worker thread"
            raise RuntimeError(msg)

        loop_factory = self.__loop_factory
        del self.__loop_factory
        coro = self.__worker()

        try:
            _run_loop(coro, loop_factory)
        finally:
            self.__running.clear()  # Cleared before the loop is dropped: "running" always implies a loop.
            self.__tasks = None
            self.__slots = None
            self.__drain = None
            self.__loop = None

    async def __worker(self) -> None:
        """Set the loop up, wait for `join`, then drain every submission before returning."""
        loop = asyncio.get_running_loop()

        if self.__exception_handler is not None:
            loop.set_exception_handler(self.__exception_handler)

        del self.__exception_handler
        self.__tasks = set()
        self.__drain = asyncio.Event()
        self.__slots = asyncio.Semaphore(self.__concurrency) if self.__concurrency > 0 else None
        del self.__concurrency
        self.__loop = loop
        self.__running.set()

        await self.__drain.wait()

        while self.__tasks:  # Looped: a task can register while an earlier gather is running.
            await asyncio.gather(*self.__tasks, return_exceptions=True)

    def is_started(self) -> bool:
        """Tell whether `run` has ever started the thread; never goes back."""
        return self.__thread is not None

    def is_running(self) -> bool:
        """Tell whether the worker can accept work right now (not merely alive and starting)."""
        thread = self.__thread
        return thread is not None and thread.is_alive() and self.__running.is_set()

    def is_stopping(self) -> bool:
        """Tell whether `join` has been called; never goes back."""
        return self.__stopping

    def is_finished(self) -> bool:
        """Tell whether the worker's thread has run and ended for good."""
        thread = self.__thread
        return thread is not None and not thread.is_alive()

    def get_loop(self) -> asyncio.AbstractEventLoop:
        """Return the worker's loop, unable to be stopped or closed from outside.

        Returns:
            A proxy of the loop.

        Raises:
            RuntimeError: If the worker or its loop is not running, or the loop is closed.
        """
        loop = self.__loop

        if loop is None or not self.is_running():
            msg = "Worker not running"
            raise RuntimeError(msg)

        if not loop.is_running():
            msg = "the worker's event loop is not running -- nothing scheduled on it would ever execute"
            raise RuntimeError(msg)

        if loop.is_closed():
            msg = "the worker's event loop is already closed -- the worker cannot accept any further work"
            raise RuntimeError(msg)

        return self.__loop_proxy

    def run(self, wait: Number | None = None) -> None:
        """Start the worker thread; a no-op while it is alive.

        Args:
            wait: Seconds to wait until it can accept work; `None` returns at once.

        Raises:
            RuntimeError: If the worker was stopped or has finished.
        """

        def _on_thread_death(exc: BaseException) -> None:
            """Keep the cause for `wait_for_running`, and log it.

            Args:
                exc: The exception that ended the thread.
            """
            self.__thread_exc = exc
            log.error("AioThreadWorker thread died", exc_info=exc)

        from ..callable_tools import safe_call  # `callable_tools` imports `async_tools`, so not at module level.

        with self.__lock:
            started_thread = self.__thread

            if started_thread is None:
                if self.is_stopping():
                    msg = "worker has already been asked to stop and cannot be started; create a new AioThreadWorker instead"
                    raise RuntimeError(msg)

                thread = threading.Thread(
                    target=safe_call, args=(self.__bootstrap,), kwargs={"log_exc": _on_thread_death},
                    name=self.__name, daemon=True,
                )
                thread.start()
                self.__thread = thread
                self.__thread_ready.set()
                del self.__name
            elif not started_thread.is_alive():
                msg = "worker is finished and cannot be restarted; create a new AioThreadWorker instead"
                raise RuntimeError(msg)

        if wait is not None:
            self.wait_for_running(wait)

    def wait_for_running(self, timeout: Number | None = None) -> None:
        """Block until the worker accepts work; never call it from inside an event loop.

        Args:
            timeout: Seconds to wait; `None` for no limit.

        Raises:
            RuntimeError: If it was never started, is called from its own thread, or its thread died.
            TimeoutError: If it is not running in time.
        """
        thread = self.__thread

        if thread is None:
            msg = "worker has not been started -- call run() first (or construct with run_now=True)"
            raise RuntimeError(msg)

        if self.is_running():
            return

        if threading.current_thread() is thread:
            msg = "cannot wait for the worker to start from inside the worker's own thread -- it would block forever"
            raise RuntimeError(msg)

        deadline = None if timeout is None else time.monotonic() + timeout

        while not self.__running.wait(0.005):  # Polled, so a thread dying during startup is reported promptly.
            if not thread.is_alive():
                msg = "worker thread ended before it ever started running"
                raise RuntimeError(msg) from self.__thread_exc

            if deadline is not None and time.monotonic() >= deadline:
                msg = f"worker did not start running within {timeout!r} seconds"
                raise TimeoutError(msg)

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
        if threading.current_thread() is self.__thread:
            msg = "cannot join from inside the worker's own thread -- waiting for it to drain would deadlock"
            raise RuntimeError(msg)

        with self.__lock:
            was_stopping = self.__stopping
            self.__stopping = True

        thread = self.__thread

        if thread is None:
            return

        if not was_stopping:
            await to_thread(self.wait_for_running)
            loop = self.__loop
            drain = self.__drain

            # `__bootstrap` clears `__loop` and `__drain` only after the drain set below, so both
            # are published here; the check only narrows their `| None` for the checker.
            if loop is not None and drain is not None:
                loop.call_soon_threadsafe(drain.set)  # `asyncio.Event` is not thread-safe.

        if not thread.is_alive():
            return

        await to_thread(partial(thread.join, timeout))

        if timeout is not None and thread.is_alive():
            msg = f"worker did not stop within {timeout!r} seconds"
            raise TimeoutError(msg)

    def __await__(self) -> Generator[Any, None, None]:
        """Await the worker to `join` it."""
        return self.join().__await__()

    async def submit(self, func: Callable[_P, Awaitable[_T]], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
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
            work = _run_tracked(func, args, kwargs, self.__tasks, self.__slots)

            if asyncio.get_running_loop() == loop:
                return await work

            return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(work, loop))
        except asyncio.CancelledError:
            cancelling = getattr(asyncio.current_task(), "cancelling", None)

            if cancelling is not None and cancelling() == 0 and (self.is_stopping() or not self.is_running()):
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
