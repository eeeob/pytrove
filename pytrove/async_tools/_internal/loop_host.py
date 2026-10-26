"""A private event loop on its own thread: its lifecycle, and the lock-free bridge into it.

Built from single-owner pieces: `_LoopLifecycle` (the phase and the thread, the
only writer of `_LoopState`) and `_LoopWork` (what lives on the loop). `_LoopHost`
runs the loop and bridges callers' threads to it; it decides nothing about the
phase itself, it asks the snapshot.
"""

from __future__ import annotations as _annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

from ..._internal import _HARD_PROPAGATE, _get_running_loop
from .loop_lifecycle import _LoopLifecycle
from .loop_work import _LoopWork
from .threads import _check_loop_factory, _close_if_unstarted, _run_loop

if TYPE_CHECKING:
    import concurrent.futures
    from collections.abc import Awaitable, Callable, Coroutine

    from ...typings import Number, _T
    from .loop_state import _LoopState


class _LoopHost:
    """Own one thread running a private event loop until a drain is requested.

    The thread starts once, ever. The phase only moves one way (see
    `_LoopState`), always through `_LoopLifecycle` under its lock; scheduling is
    lock-free, so any number of threads submit at once. The drain waits for every
    tracked submission, and nothing submitted runs after it. What ended the thread
    is returned by `_stop`, never logged. `AioThreadWorker` inherits it;
    `SyncAwaitableRunner` wraps it.
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

        # Settings, read once by the loop thread when the loop starts.
        self._concurrency = concurrency
        self._loop_factory = loop_factory
        self._exception_handler = exception_handler

        self._lifecycle = _LoopLifecycle(name)
        """The one authority over the phase; every lifecycle question and move goes through it."""

        self._pending: dict[concurrent.futures.Future[Any], Coroutine[Any, Any, Any]] = {}
        """Futures `_schedule` handed out whose task may not exist yet, each with its coroutine.

        A dying loop cancels each future and closes its coroutine if it never started,
        so nothing hangs and nothing warns it was never awaited. Must stay a built-in
        `dict`: on free-threaded builds, setting an item and `copy` take the same
        per-object lock, which is what orders `_schedule` against `_bootstrap`.
        """

        if run_now:
            self.run()

    # -- Lifecycle: callers' threads -----------------------------------------------------

    def run(self, wait: Number | None = None) -> None:
        """Start the worker thread; a worker starts once, ever, so a second call always raises.

        Runs on: any thread.

        Args:
            wait: Seconds to wait until it can accept work; `None` returns at once.

        Raises:
            RuntimeError: If it was already started, stopped or finished, or the thread
                could not be started (final: it is never retried).
        """
        self._lifecycle.start(self._bootstrap, again_ok=False)

        if wait is not None:
            self.wait_for_running(wait)

    def _ensure_started(self) -> None:
        """Start the thread unless it already started; for `async with` and a lazy runner.

        Runs on: any thread.

        Raises:
            RuntimeError: If it was stopped or finished, or the thread could not be started.
        """
        self._lifecycle.start(self._bootstrap, again_ok=True)

    def wait_for_running(self, timeout: Number | None = None) -> None:
        """Block until the worker accepts work; never call it from inside an event loop.

        Runs on: any thread but the worker's.

        Args:
            timeout: Seconds to wait; `None` for no limit.

        Raises:
            RuntimeError: If it was never started, is called from its own thread, was stopped
                while starting, or its thread ended (chained from what ended it).
            TimeoutError: If it is not running in time.
        """
        self._lifecycle.wait_for_running(timeout)

    def _state(self) -> _LoopState:
        """Return the current lifecycle snapshot; take every decision from one.

        Runs on: any thread, without a lock.
        """
        return self._lifecycle.state

    def is_started(self) -> bool:
        """Tell whether the single start was used; never goes back."""
        return self._state().started

    def is_running(self) -> bool:
        """Tell whether the loop is up (draining included; not merely alive and starting)."""
        return self._state().running

    def is_stopping(self) -> bool:
        """Tell whether a stop was requested; never goes back."""
        return self._state().stopping

    def is_finished(self) -> bool:
        """Tell whether the loop is over for good; its thread is exiting or gone."""
        return self._state().finished

    def _stop(self, timeout: Number | None = None) -> BaseException | None:
        """Refuse new work, let the submissions drain, then wait for the thread; safe to repeat.

        Runs on: any thread but the worker's.

        Args:
            timeout: Seconds for the final wait on the thread only.

        Returns:
            What ended the thread or failed to start it, the same every time; `None` after
            a clean end, or for a worker that never started (which now never will).

        Raises:
            TimeoutError: If the thread is still alive after `timeout`.
        """
        work = self._lifecycle.request_stop()

        if work is not None:
            with contextlib.suppress(RuntimeError):  # The loop closed meanwhile: nothing to drain.
                work.request_drain()

        return self._lifecycle.join(timeout)

    # -- The loop thread -----------------------------------------------------------------

    def _bootstrap(self) -> None:
        """Run the loop for the worker's whole life, then fail whatever it left pending.

        Runs on: the worker thread only, as its body.

        Raises:
            RuntimeError: If called from any other thread.
        """
        lifecycle = self._lifecycle

        if not lifecycle.is_current():
            msg = "Bootstrap must be called from the worker thread"
            raise RuntimeError(msg)

        death: BaseException | None = None

        try:
            _run_loop(self._host(), self._loop_factory)
        except _HARD_PROPAGATE as exc:
            death = exc
            raise  # `SystemExit` and `KeyboardInterrupt` are never swallowed.
        except BaseException as exc:  # noqa: BLE001 - a dying thread has no caller; `_stop` returns it
            death = exc
        finally:
            # The order is the handshake with `_schedule`; do not reorder:
            # (1) unpublish the loop, so a `_schedule` that adds after the sweep sees it gone;
            # (2) sweep, so a `_schedule` that added before (1) is cancelled here.
            lifecycle.end(death)

            for (
                fut,
                coro,
            ) in self._pending.copy().items():  # One locked copy, never a live iteration.
                self._drop(fut, coro)

    async def _host(self) -> None:
        """Build the loop's state, publish it, then sleep until drained.

        Runs on: the worker's loop, as its main coroutine.
        """
        loop = asyncio.get_running_loop()
        work = _LoopWork(loop, self._concurrency)

        if self._exception_handler is not None:
            loop.set_exception_handler(self._exception_handler)

        if not self._lifecycle.publish(work):
            return  # A stop came during startup: serve nothing.

        try:
            await work.wait_drained()
        finally:
            work.closed = True  # Drained or dying: nothing scheduled from now on runs.

    # -- The bridge: any thread, lock-free -----------------------------------------------

    def _checked_work(self, *, new_work: bool = True) -> _LoopWork:
        """Return the loop's state, once the loop is sure to run what is scheduled on it.

        Runs on: any thread.

        Args:
            new_work: Whether a new submission is meant, which a stopping worker refuses;
                `False` only to hand out the (possibly draining) loop.

        Returns:
            The published loop state.

        Raises:
            RuntimeError: The phase's refusal (see `_LoopState.checked_work`), or a loop that
                is not running or already closed.
        """
        work = self._state().checked_work(new_work=new_work)  # The one load of the snapshot.

        if not work.loop.is_running():
            msg = "the worker's event loop is not running -- nothing scheduled on it would ever execute"
            raise RuntimeError(msg)

        if work.loop.is_closed():
            msg = "the worker's event loop is already closed -- the worker cannot accept any further work"
            raise RuntimeError(msg)

        return work

    def _schedule(
        self, func: Callable[..., Awaitable[_T]], args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> concurrent.futures.Future[_T]:
        """Schedule a tracked submission on the loop from another thread, without a lock.

        Runs on: any thread but the worker's.

        Args:
            func: The awaitable function, called on the loop.
            args: Its positional arguments.
            kwargs: Its keyword arguments.

        Returns:
            The future of its outcome; cancelled if the loop ends before running it.

        Raises:
            RuntimeError: If the worker cannot accept work (see `_checked_work`).
        """
        work = self._checked_work()
        coro = work.run(func, args, kwargs)

        try:
            fut = work.schedule(coro)
        except BaseException:
            coro.close()  # Refused by a loop closing meanwhile: never left unawaited.
            raise

        # The order is the handshake with `_bootstrap`; do not reorder: publish the future,
        # then look again. Either the sweep finds it, or this check sees the loop gone.
        self._pending[fut] = coro
        fut.add_done_callback(self._forget)

        if self._state().work is None:
            self._drop(fut, coro)  # Harmless if the sweep dropped it too.

        return fut

    def _forget(self, fut: concurrent.futures.Future[Any]) -> None:
        """Stop tracking a future once it is done.

        Runs on: whichever thread completes `fut`.
        """
        self._pending.pop(fut, None)

    @staticmethod
    def _drop(fut: concurrent.futures.Future[Any], coro: Coroutine[Any, Any, Any]) -> None:
        """Cancel a future the gone loop will never complete, and close its coroutine if unstarted.

        Runs on: any thread, only once the loop is closed (`work` unpublished), so the
        loop can no longer start `coro` while it is being closed.
        """
        fut.cancel()
        _close_if_unstarted(coro)

    def _on_own_loop(self) -> bool:
        """Tell whether the caller runs on the worker's loop, where work can run inline.

        Runs on: any thread.
        """
        work = self._state().work
        return work is not None and _get_running_loop() is work.loop

    def _on_own_thread(self) -> bool:
        """Tell whether the caller is the worker's thread, where waiting on it would deadlock."""
        return self._lifecycle.is_current()


__all__ = ("_LoopHost",)
