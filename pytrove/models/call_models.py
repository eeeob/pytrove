"""Calls stored now and run later: on a result, or after a delay."""

from __future__ import annotations as _annotations

import asyncio
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from ..async_tools import maybe_awaitable, safe_wait_task
from ..enums import TriggerOn
from ..typings import MaybeAwaitable, MaybeCoroutineCallable, Number, _T
from ..validate_tools import is_exception

if TYPE_CHECKING:
    from concurrent.futures import ThreadPoolExecutor


@dataclass(slots=True)
class DeferredCall(Generic[_T]):
    """A call kept for later, run only when a result matches `when`."""

    func: MaybeAwaitable[..., _T]
    """The sync or async callable to run; a sync one runs in `run()`'s executor."""

    args: tuple[Any, ...] | None = None
    """Positional arguments stored with the call, placed before the ones `run()` receives."""

    kw: Mapping[str, Any] | None = None
    """Keyword arguments stored with the call; the ones `run()` receives override them."""

    when: TriggerOn = TriggerOn.SUCCESS
    """Which results trigger the call: a success, an exception, or any."""

    def should_run(self, r: Any) -> bool:
        """Return whether the result `r` triggers this call.

        Args:
            r: A result, or the exception raised in its place.

        Returns:
            `True` if `when` covers `r`.
        """
        when = self.when

        return (
            when == TriggerOn.ALWAYS
            or (is_exception(r) and when == TriggerOn.ERROR)
            or (not is_exception(r) and when == TriggerOn.SUCCESS)
        )

    async def run(self, *args: Any, executor: ThreadPoolExecutor | None = None, **kw: Any) -> _T:
        """Run `func` with the stored arguments plus the ones given here.

        Positional arguments here come after the stored ones, and a keyword
        given both here and at construction takes the value given here.

        Args:
            *args: Extra positional arguments.
            executor: The executor a sync `func` runs in.
            **kw: Extra keyword arguments.

        Returns:
            What `func` returns.
        """
        call_args = (*(self.args or ()), *args)
        call_kw = {**(self.kw or {}), **kw}

        return await maybe_awaitable(self.func, *call_args, **call_kw, executor=executor)


@dataclass(slots=True)
class DelayedCallback(Generic[_T]):
    """A callback run once `delay` seconds pass, unless it is cancelled first."""

    delay: Number
    """Seconds to wait before running `callback`."""

    callback: MaybeAwaitable[..., _T]
    """The sync or async callable to run."""

    args: tuple[Any, ...] | None = None
    """Positional arguments for `callback`."""

    kw: Mapping[str, Any] | None = None
    """Keyword arguments for `callback`."""

    on_finished: MaybeCoroutineCallable[[Self], Any] | None = None
    """Called with this instance once the wait ends, however it ended; an error it raises is logged, not raised."""

    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    """Set to cancel the callback before it starts, by `cancel()` even before `start()`; `wait()` blocks on it for `delay`."""

    callback_started: bool = field(default=False, init=False)
    """Whether the delay ran out and the callback began; a non-forced `cancel()` then lets it finish."""

    _task: asyncio.Task[_T | None] | None = field(default=None, init=False, repr=False)
    """The task `start()` created, cleared by `cancel()`."""

    async def wait(self) -> _T | None:
        """Wait out `delay`, then run `callback`, unless `cancel_event` is set first.

        The wait is on `cancel_event`: timing out on it is the path that runs
        the callback, and the event firing means cancelled. The callback runs
        after the timeout is handled, so its own error carries no
        `TimeoutError` context.

        Returns:
            What `callback` returns, or `None` if it was cancelled.
        """
        try:
            try:
                await asyncio.wait_for(self.cancel_event.wait(), timeout=self.delay)
            except asyncio.TimeoutError:
                pass
            else:
                return None

            self.callback_started = True
            return await maybe_awaitable(self.callback, *(self.args or ()), **(self.kw or {}))

        finally:
            if self.on_finished is not None:
                await maybe_awaitable(self.on_finished, self, return_exc=True)

    def start(self) -> asyncio.Task[_T | None]:
        """Start `wait()` as a task, once.

        Returns:
            The task; the same one on every call.
        """
        if self._task is None:
            self._task = asyncio.create_task(self.wait())

        return self._task

    async def cancel(self, force: bool = False) -> None:
        """Stop the callback, and wait for its task to end.

        Before `start()` or during the delay this always keeps the callback
        from starting. Once it has started, it is cancelled only with `force`.
        `callback_started` is set just before the callback is awaited, so a
        narrow window exists where a non-forced cancel lets a callback that
        has not run a line yet go ahead.

        Args:
            force: Cancel the callback even if it has already started.

        Raises:
            Exception: Whatever a started callback raises, when it is let finish.
        """
        self.cancel_event.set()

        task = self._task

        if task is None:
            return

        if not task.done():
            if force or not self.callback_started:
                task.cancel()

            await safe_wait_task(task)

        self._task = None

    @property
    def task(self) -> asyncio.Task[_T | None] | None:
        """The running task, or `None` if not started."""
        return self._task

    @property
    def started(self) -> bool:
        """Whether `start()` created a task that `cancel()` has not cleared."""
        return self._task is not None

    @property
    def done(self) -> bool:
        """Whether the task has finished."""
        return self._task is not None and self._task.done()

    @property
    def cancelled(self) -> bool:
        """Whether `cancel_event` is set."""
        return self.cancel_event.is_set()


__all__ = (
    "DeferredCall",
    "DelayedCallback",
)
