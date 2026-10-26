"""A loop host's lifecycle as data: its phases, one immutable snapshot, and every refusal.

This module knows neither `threading` nor `asyncio`. It is the single place that
says what each phase means, where each move leads, and why a phase refuses
something; `_LoopLifecycle` performs the moves and everyone else only asks.
"""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, Final, Literal, NamedTuple, TypeAlias

if TYPE_CHECKING:
    from .loop_work import _LoopWork

_Phase: TypeAlias = Literal[
    "new", "starting", "running", "stopping", "stopped", "dead", "abandoned"
]
"""Where a loop host is in its one-way life; the moves are `_ON_STOP`, `_ON_END` and `_LoopLifecycle`."""

_ON_STOP: Final[dict[_Phase, _Phase]] = {
    "new": "abandoned",  # Never started, so now it never will.
    "starting": "stopping",  # `publish` then refuses, and the loop serves nothing.
    "running": "stopping",  # The loop drains what it accepted.
    "stopping": "stopping",
    "stopped": "stopped",
    "dead": "stopped",  # Ended on its own; now also asked to stop.
    "abandoned": "abandoned",
}
"""Where a stop request moves each phase; total, so a repeated stop changes nothing."""

_ON_END: Final[dict[_Phase, _Phase]] = {
    "new": "new",  # Unreachable, as is `abandoned`: no thread runs there. Kept so the table is total.
    "starting": "dead",
    "running": "dead",
    "stopping": "stopped",
    "stopped": "stopped",
    "dead": "dead",
    "abandoned": "abandoned",
}
"""Where the thread's end moves each phase; total, so the end never fails."""

_START_REFUSALS: Final[dict[_Phase, str]] = {
    "starting": "worker is already started -- run() starts it only once",
    "running": "worker is already started -- run() starts it only once",
    "stopping": "worker is stopping and cannot be started again; create a new AioThreadWorker instead",
    "stopped": "worker is finished and cannot be restarted; create a new AioThreadWorker instead",
    "dead": "worker is finished and cannot be restarted; create a new AioThreadWorker instead",
    "abandoned": "worker has already been asked to stop and cannot be started; create a new AioThreadWorker instead",
}
"""Why each phase but `new` refuses a start."""

_REFUSALS: Final[dict[_Phase, str]] = {  # No `running`: a running phase always has its loop.
    "new": "worker has not been started -- call run() first",
    "starting": "worker is not running yet -- wait_for_running() waits for it",
    "stopping": "worker is stopping",
    "stopped": "worker is closed",
    "dead": "worker is closed: its thread ended",
    "abandoned": "worker is closed: it was stopped before it ever started",
}
"""Why each phase refuses the loop, or new work on it."""


class _LoopState(NamedTuple):
    """One immutable snapshot of a loop host's lifecycle; every question is answered from one.

    Only `_LoopLifecycle` builds new ones, under its lock. Anyone may read one
    without a lock: nothing in it ever changes, so a decision taken from one
    snapshot is always self-consistent.
    """

    phase: _Phase
    """Where the host is in its one-way life."""

    work: _LoopWork | None = None
    """The loop's state while the loop is up (running, then draining while stopping); else `None`."""

    death: BaseException | None = None
    """What ended the thread, or failed to start it; `None` while alive or after a clean end."""

    @property
    def started(self) -> bool:
        """Whether the single start was used; never goes back."""
        return self.phase not in ("new", "abandoned")

    @property
    def running(self) -> bool:
        """Whether the loop is up, draining included."""
        return self.work is not None

    @property
    def accepting(self) -> bool:
        """Whether the loop takes new work: up, and no stop requested."""
        return self.phase == "running"

    @property
    def stopping(self) -> bool:
        """Whether a stop was requested; never goes back."""
        return self.phase in ("stopping", "stopped", "abandoned")

    @property
    def finished(self) -> bool:
        """Whether the loop is over for good; its thread is exiting or gone."""
        return self.phase in ("stopped", "dead")

    @property
    def gone(self) -> bool:
        """Whether work handed to the loop may have been dropped: stopping, or no loop at all."""
        return self.stopping or self.work is None

    @property
    def needs_start(self) -> bool:
        """Whether a lazy caller still has to start the thread, or wait for its start."""
        return self.phase in ("new", "starting")

    def start_refusal(self, *, again_ok: bool) -> str | None:
        """Say why the thread may not be started now, or `None` when it may.

        Args:
            again_ok: Whether a thread already starting or running is fine rather than refused.

        Returns:
            The phase's refusal, or `None`.
        """
        if self.phase == "new" or (again_ok and self.phase in ("starting", "running")):
            return None

        return _START_REFUSALS[self.phase]

    def checked_work(self, *, new_work: bool) -> _LoopWork:
        """Return the loop's state if it may be used now.

        Args:
            new_work: Whether a new submission is meant; a stopping host still hands out its
                draining loop, but refuses new work on it.

        Returns:
            The loop's state.

        Raises:
            RuntimeError: With the phase's refusal, chained from the death.
        """
        work = self.work

        if work is None or (new_work and self.phase != "running"):
            msg = _REFUSALS[self.phase]
            raise RuntimeError(msg) from self.death

        return work


__all__ = ("_ON_END", "_ON_STOP", "_LoopState", "_Phase")
