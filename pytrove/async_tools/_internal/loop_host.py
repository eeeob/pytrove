"""The thread-and-loop half of `AioThreadWorker`: starting, state and loop access."""

from __future__ import annotations as _annotations

import asyncio
import logging
import threading
import time
from functools import cached_property
from typing import TYPE_CHECKING, Any

from .threads import _check_loop_factory, _run_loop

if TYPE_CHECKING:
    from collections.abc import Callable

    from ...typings import Number

log = logging.getLogger("pytrove.async_tools.worker")


class _LoopHost:
    """Own one thread running a private event loop until a drain is requested.

    Only lifecycle transitions take the lock: state only moves one way, and
    the loop is published before "running" is set. `AioThreadWorker` adds
    submission and shutdown on top.
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
        if not isinstance(
            concurrency, int
        ):  # A bool passes on purpose: `True` reads as a cap of 1.
            msg = f"concurrency must be an int, got {type(concurrency).__name__!r}"
            raise TypeError(msg)

        if exception_handler is not None and not callable(exception_handler):
            msg = f"exception_handler must be callable, got {type(exception_handler).__name__!r}"
            raise TypeError(msg)

        _check_loop_factory(loop_factory)

        self._name = name
        self._concurrency = concurrency
        self._loop_factory = loop_factory
        self._exception_handler = exception_handler
        self._lock = threading.RLock()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: set[asyncio.Task[Any]] | None = None
        self._slots: asyncio.Semaphore | None = None
        self._drain: asyncio.Event | None = None
        self._stopping = False
        self._thread_exc: BaseException | None = None

        if run_now:
            self.run()

    @cached_property
    def _loop_proxy(self) -> Any:
        """The loop handed to callers, with `close` and `stop` denied so its lifecycle stays the worker's.

        Raises:
            RuntimeError: If the loop is not published yet.
        """
        if self._loop is None:
            msg = "the worker's event loop has not been published yet -- use get_loop(), which waits on that"
            raise RuntimeError(msg)

        from ...object_tools.proxies import WeakRestrictedProxy  # noqa: PLC0415 - `object_tools` sits above `async_tools`

        return WeakRestrictedProxy(self._loop, blocked=["close", "stop"])

    def _bootstrap(self) -> None:
        """Run the loop for the worker's whole life, on the worker thread.

        Raises:
            RuntimeError: If called from any other thread.
        """
        self._thread_ready.wait()  # `run` publishes `_thread` only after starting it.

        if threading.current_thread() is not self._thread:
            msg = "Bootstrap must be called from the worker thread"
            raise RuntimeError(msg)

        loop_factory = self._loop_factory
        del self._loop_factory
        coro = self._host()

        try:
            _run_loop(coro, loop_factory)
        finally:
            self._running.clear()  # Cleared before the loop is dropped: "running" always implies a loop.
            self._tasks = None
            self._slots = None
            self._drain = None
            self._loop = None

    async def _host(self) -> None:
        """Set the loop up, wait for `join`, then drain every submission before returning."""
        loop = asyncio.get_running_loop()

        if self._exception_handler is not None:
            loop.set_exception_handler(self._exception_handler)

        del self._exception_handler
        self._tasks = set()
        self._drain = asyncio.Event()
        self._slots = asyncio.Semaphore(self._concurrency) if self._concurrency > 0 else None
        del self._concurrency
        self._loop = loop
        self._running.set()

        await self._drain.wait()

        while self._tasks:  # Looped: a task can register while an earlier gather is running.
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def is_started(self) -> bool:
        """Tell whether `run` has ever started the thread; never goes back."""
        return self._thread is not None

    def is_running(self) -> bool:
        """Tell whether the worker can accept work right now (not merely alive and starting)."""
        thread = self._thread
        return thread is not None and thread.is_alive() and self._running.is_set()

    def is_stopping(self) -> bool:
        """Tell whether `join` has been called; never goes back."""
        return self._stopping

    def is_finished(self) -> bool:
        """Tell whether the worker's thread has run and ended for good."""
        thread = self._thread
        return thread is not None and not thread.is_alive()

    def get_loop(self) -> asyncio.AbstractEventLoop:
        """Return the worker's loop, unable to be stopped or closed from outside.

        Returns:
            A proxy of the loop.

        Raises:
            RuntimeError: If the worker or its loop is not running, or the loop is closed.
        """
        loop = self._loop

        if loop is None or not self.is_running():
            msg = "Worker not running"
            raise RuntimeError(msg)

        if not loop.is_running():
            msg = "the worker's event loop is not running -- nothing scheduled on it would ever execute"
            raise RuntimeError(msg)

        if loop.is_closed():
            msg = "the worker's event loop is already closed -- the worker cannot accept any further work"
            raise RuntimeError(msg)

        return self._loop_proxy

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
            self._thread_exc = exc
            log.error("AioThreadWorker thread died", exc_info=exc)

        from ...callable_tools import safe_call  # noqa: PLC0415 - `callable_tools` imports `async_tools`

        with self._lock:
            started_thread = self._thread

            if started_thread is None:
                if self.is_stopping():
                    msg = "worker has already been asked to stop and cannot be started; create a new AioThreadWorker instead"
                    raise RuntimeError(msg)

                thread = threading.Thread(
                    target=safe_call,
                    args=(self._bootstrap,),
                    kwargs={"log_exc": _on_thread_death},
                    name=self._name,
                    daemon=True,
                )
                thread.start()
                self._thread = thread
                self._thread_ready.set()
                del self._name
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
        thread = self._thread

        if thread is None:
            msg = "worker has not been started -- call run() first (or construct with run_now=True)"
            raise RuntimeError(msg)

        if self.is_running():
            return

        if threading.current_thread() is thread:
            msg = "cannot wait for the worker to start from inside the worker's own thread -- it would block forever"
            raise RuntimeError(msg)

        deadline = None if timeout is None else time.monotonic() + timeout

        while not self._running.wait(
            0.005
        ):  # Polled, so a thread dying during startup is reported promptly.
            if not thread.is_alive():
                msg = "worker thread ended before it ever started running"
                raise RuntimeError(msg) from self._thread_exc

            if deadline is not None and time.monotonic() >= deadline:
                msg = f"worker did not start running within {timeout!r} seconds"
                raise TimeoutError(msg)


__all__ = ("_LoopHost",)
