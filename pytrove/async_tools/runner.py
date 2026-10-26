"""A persistent event loop on a background thread, for running awaitables from sync code."""

from __future__ import annotations as _annotations

import concurrent.futures
import sys
from typing import TYPE_CHECKING

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from ._internal import _close_if_unstarted, _check_loop_factory, _LoopHost
from .run import run_awaitable_in_coro

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Awaitable, Callable

    from ..typings import Number, _T


class SyncAwaitableRunner:
    """Keeps one event loop alive on a background thread and runs awaitables on it from sync code.

    Unlike `run_awaitable_sync`, which builds a loop per call, state bound to
    the loop survives between `run` calls. `close` lets every awaitable passed
    to `run` finish; any other task still on the loop then is cancelled. A
    `run` that loses the race with `close` raises `RuntimeError`, never hangs.

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
            RuntimeError: If the loop fails to start.
        """
        _check_loop_factory(loop_factory)
        # Before 3.12 the factory is ignored, and the check above already warned about it.
        factory = loop_factory if sys.version_info >= (3, 12) else None
        self.__host = _LoopHost(name=name, loop_factory=factory, run_now=False)

        if not lazy:
            self.start()

    @property
    def started(self) -> bool:
        """Whether the thread was ever started; never goes back."""
        return self.__host.is_started()

    @property
    def running(self) -> bool:
        """Whether the loop is up and accepting work (not starting, not draining).

        Narrower than `AioThreadWorker.is_running()`, which stays true while the loop drains.
        """
        return self.__host._state().accepting

    @property
    def closed(self) -> bool:
        """Whether `close` has been called; never goes back."""
        return self.__host.is_stopping()

    def start(self) -> None:
        """Start the background thread and block until its loop is ready; it starts once, ever.

        Raises:
            RuntimeError: If it is already started, closed or ended, or its loop fails to start.
        """
        name = self.__class__.__name__
        state = self.__host._state()

        if state.stopping:
            msg = f"{name} is closed"
            raise RuntimeError(msg)

        if state.phase == "dead":
            msg = f"{name}'s event loop has ended"
            raise RuntimeError(msg) from state.death

        if state.started:
            msg = f"{name} is already started"
            raise RuntimeError(msg)

        self.__start(self.__host.run)

    def __start(self, start: Callable[[], object]) -> None:
        """Call `start`, then block until the loop runs, naming this runner in any failure.

        Args:
            start: The host's strict `run`, or its tolerant `_ensure_started`.

        Raises:
            RuntimeError: "is closed" if a `close` won the race, "is already started" if another
                thread's start won it, else "failed to start", chained from the host's reason.
        """
        try:
            start()
            self.__host.wait_for_running()
        except RuntimeError as exc:
            name = self.__class__.__name__
            state = self.__host._state()

            if state.stopping:
                msg = f"{name} is closed"
            elif state.phase in ("starting", "running"):  # Only a strict second start fails here.
                msg = f"{name} is already started"
            else:
                msg = f"{name}'s event loop failed to start"

            raise RuntimeError(msg) from exc

    def run(self, awaitable: Awaitable[_T]) -> _T:
        """Run an awaitable on the loop and block until it completes, starting the loop if needed.

        A refused coroutine is closed. An interruption of the wait, such as
        `KeyboardInterrupt`, cancels the awaitable too.

        Args:
            awaitable: The awaitable.

        Returns:
            Its result.

        Raises:
            RuntimeError: If the runner is closed or not running, its loop fails to
                start, it is called from the runner's own thread (it would deadlock),
                or the runner stops before the awaitable completes.
        """
        host = self.__host
        name = self.__class__.__name__

        try:
            if host._on_own_thread():
                msg = "cannot run from inside the runner's own thread -- waiting for it would deadlock"
                raise RuntimeError(msg)

            if host._state().needs_start:  # Lazy: start it, or wait for a start under way.
                self.__start(host._ensure_started)

            state = host._state()

            if not state.accepting:
                msg = f"{name} is closed" if state.stopping else f"{name} is not running"
                raise RuntimeError(msg) from state.death

            try:
                fut = host._schedule(run_awaitable_in_coro, (awaitable,), {})
            except RuntimeError as exc:
                if not host._state().stopping:
                    raise

                msg = f"{name} is closed"  # A `close` won the race after the check above.
                raise RuntimeError(msg) from exc
        except BaseException:
            _close_if_unstarted(awaitable)
            raise

        try:
            return fut.result()
        except concurrent.futures.CancelledError:
            if host._state().gone:
                _close_if_unstarted(awaitable)  # The task is done, or the loop is gone.
                msg = f"{name} stopped before this awaitable completed"
                raise RuntimeError(msg) from None

            raise
        except BaseException:
            fut.cancel()  # The wait was interrupted: cancel the awaitable too.
            raise

    __call__ = run

    def close(self, timeout: Number | None = None) -> BaseException | None:
        """Let every awaitable passed to `run` finish, cancel what else is left, and stop; safe to repeat.

        Args:
            timeout: Seconds for the final wait on the thread only; `None` for no limit.

        Returns:
            What ended the loop's thread or failed to start it, the same every time; `None`
            after a clean stop or for a runner never started. It is never raised.

        Raises:
            RuntimeError: If called from the runner's own thread.
            TimeoutError: If the thread is still alive after `timeout`.
        """
        if self.__host._on_own_thread():
            msg = (
                "cannot close from inside the runner's own thread -- waiting for it would deadlock"
            )
            raise RuntimeError(msg)

        try:
            return self.__host._stop(timeout)
        except TimeoutError:
            msg = f"{self.__class__.__name__} did not close within {timeout!r} seconds"
            raise TimeoutError(msg) from None

    def __enter__(self) -> Self:
        """Use the runner as a context manager.

        Returns:
            The runner.
        """
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close the runner; what ended its thread is not raised (call `close` to get it).

        Args:
            *exc_info: The exception, if any; not suppressed.
        """
        self.close()


__all__ = ("SyncAwaitableRunner",)
