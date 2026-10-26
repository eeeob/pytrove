"""The one authority over a loop host's lifecycle: its phase, its single thread, and every move.

This module knows `threading` only, never `asyncio`. Every change of phase
happens here, under one lock, by publishing a new `_LoopState`; every other
module only reads that snapshot.
"""

from __future__ import annotations as _annotations

import threading
from typing import TYPE_CHECKING

from .loop_state import _ON_END, _ON_STOP, _LoopState

if TYPE_CHECKING:
    from collections.abc import Callable

    from ...typings import Number
    from .loop_work import _LoopWork


class _LoopLifecycle:
    """Hold the phase as one published `_LoopState`, and make every move between phases.

    Every move replaces `state` while holding `_changed`, then wakes its
    waiters; nothing else ever writes `state`. A reader off the lock loads
    `state` once and decides from that one snapshot.
    """

    def __init__(self, name: str | None) -> None:
        """Prepare a new, unstarted lifecycle.

        Args:
            name: The thread's name; `None` lets `threading` pick one.
        """
        self.name = name
        """The name given to the thread when it starts."""

        self.state = _LoopState("new")
        """The published snapshot: replaced whole, never mutated, and only while holding `_changed`.

        Read without the lock: on free-threaded builds an instance attribute is
        stored with release and loaded with acquire, so a reader gets a whole,
        fully built snapshot.
        """

        self.thread: threading.Thread | None = None
        """The single thread, written under the lock before it runs; `None` if it never ran."""

        self._changed = threading.Condition(threading.Lock())
        """The one lifecycle lock, and the signal `wait_for_running` sleeps on."""

    def _move(self, state: _LoopState) -> None:
        """Publish `state` and wake every waiter.

        Runs on: any thread, holding `_changed`.
        """
        self.state = state
        self._changed.notify_all()

    # -- Moves ------------------------------------------------------------------------------

    def start(self, main: Callable[[], object], *, again_ok: bool) -> None:
        """Move new -> starting and start the single thread running `main`.

        Runs on: a caller's thread.

        Args:
            main: The thread's body.
            again_ok: Whether a thread already starting or running is fine (the internal path)
                rather than refused (`run`, which starts only once).

        Raises:
            RuntimeError: The phase's refusal, chained from the death; or `Thread.start` failing,
                which is final.
        """
        with self._changed:
            state = self.state
            msg = state.start_refusal(again_ok=again_ok)

            if msg is not None:
                raise RuntimeError(msg) from state.death

            if state.phase != "new":
                return  # Already starting or running, and `again_ok`.

            thread = threading.Thread(target=main, name=self.name, daemon=True)

            try:
                # Both before `Thread.start`: the thread checks `is_current` first thing.
                self.thread = thread
                self._move(_LoopState("starting"))
                thread.start()
            except BaseException as exc:
                # ponytail: an interrupt inside `Thread.start` after the OS thread began leaves
                # that thread unjoined; it fails its `is_current` check and exits. Keep the
                # handle when `thread.ident` is set if that is ever seen.
                self.thread = None
                self._move(_LoopState("dead", death=exc))  # One shot: never retried.
                raise

    def publish(self, work: _LoopWork) -> bool:
        """Move starting -> running, with the loop's state.

        Runs on: the thread, once its loop runs.

        Args:
            work: The loop's state.

        Returns:
            Whether the loop now serves; `False` when a stop came first.
        """
        with self._changed:
            if self.state.phase != "starting":
                return False

            self._move(_LoopState("running", work))
            return True

    def request_stop(self) -> _LoopWork | None:
        """Move along `_ON_STOP`; safe to repeat and to race.

        Runs on: a caller's thread.

        Returns:
            The loop to drain whenever one is up, so a drain request lost by one caller is
            made again by the next; `None` if there is no loop.
        """
        with self._changed:
            state = self.state
            self._move(state._replace(phase=_ON_STOP[state.phase]))  # `work` is kept: it drains.
            return state.work

    def end(self, death: BaseException | None) -> None:
        """Move along `_ON_END` and unpublish the loop, keeping the first death.

        Runs on: the thread, last, after its loop closed.

        Args:
            death: What ended the thread; `None` for a clean end.
        """
        with self._changed:
            state = self.state
            first = state.death if state.death is not None else death
            self._move(_LoopState(_ON_END[state.phase], None, first))

    # -- Questions and waits ----------------------------------------------------------------

    def is_current(self) -> bool:
        """Tell whether the caller is the thread.

        Runs on: any thread; a stale `None` read still answers `False` correctly.
        """
        return threading.current_thread() is self.thread

    def wait_for_running(self, timeout: Number | None = None) -> None:
        """Block, without polling, until the phase leaves starting, then require the loop.

        Runs on: any thread but this one; never from inside an event loop.

        Args:
            timeout: Seconds to wait; `None` for no limit.

        Raises:
            RuntimeError: The phase's refusal (chained from the death), or a wait from the
                thread itself.
            TimeoutError: If it is still starting after `timeout`.
        """
        state = self.state

        if state.phase == "starting":
            if self.is_current():
                msg = "cannot wait for the worker to start from inside the worker's own thread -- it would block forever"
                raise RuntimeError(msg)

            with self._changed:
                if not self._changed.wait_for(lambda: self.state.phase != "starting", timeout):
                    msg = f"worker did not start running within {timeout!r} seconds"
                    raise TimeoutError(msg)

                state = self.state

        state.checked_work(new_work=False)

    def join(self, timeout: Number | None = None) -> BaseException | None:
        """Wait for the thread to end, and return what ended it.

        Runs on: any thread but this one.

        Args:
            timeout: Seconds to wait; `None` for no limit.

        Returns:
            The death, the same one every time; `None` after a clean end or if it never ran.

        Raises:
            TimeoutError: If the thread is still alive after `timeout`.
        """
        with self._changed:  # Orders this read after the start that wrote `thread`.
            thread = self.thread

        if thread is not None:
            thread.join(timeout)

            if thread.is_alive():
                msg = f"worker did not stop within {timeout!r} seconds"
                raise TimeoutError(msg)

        return self.state.death  # `end` ran before the thread exited, and `join` orders it here.


__all__ = ("_LoopLifecycle",)
