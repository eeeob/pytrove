"""Calls stored now and run later: on a result, or after a delay."""

from __future__ import annotations as _annotations

import asyncio
import sys
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Generic

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from ..async_tools import maybe_awaitable, safe_wait_task
from ..enums import TriggerOn
from ..typings import MaybeAwaitable, MaybeCoroutineCallable, Number, _T
from ..validate_tools import is_exception


@dataclass(slots=True)
class DeferredCall(Generic[_T]):
    """A call kept for later, run only when a result matches `when`.

    Attributes:
        func: The sync or async callable to run.
        args: Positional arguments stored with the call.
        kw: Keyword arguments stored with the call.
        when: Which results trigger the call: a success, an exception, or any.
    """

    func: MaybeAwaitable[..., _T]
    args: tuple[Any, ...] | None = None
    kw: Mapping[str, Any] | None = None

    when: TriggerOn = TriggerOn.SUCCESS

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
    """A callback run once `delay` seconds pass, unless it is cancelled first.

    Attributes:
        delay: Seconds to wait before running `callback`.
        callback: The sync or async callable to run.
        args: Positional arguments for `callback`.
        kw: Keyword arguments for `callback`.
        on_finished: Called with this instance once the wait ends, whether
            the callback ran, failed or was cancelled.
        cancel_event: Set to cancel the callback before it starts.
        callback_started: Whether the delay ran out and the callback began.
    """

    delay: Number
    callback: MaybeAwaitable[..., _T]

    args: tuple[Any, ...] | None = None
    kw: Mapping[str, Any] | None = None

    on_finished: MaybeCoroutineCallable[[Self], Any] | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    callback_started: bool = field(default=False, init=False)
    _task: asyncio.Task[_T | None] | None = field(default=None, init=False, repr=False)

    async def wait(self) -> _T | None:
        """Wait out `delay`, then run `callback`, unless `cancel_event` is set first.

        The wait is on `cancel_event`: timing out on it is the path that runs
        the callback, and the event firing means cancelled.

        Returns:
            What `callback` returns, or `None` if it was cancelled.
        """
        try:
            await asyncio.wait_for(self.cancel_event.wait(), timeout=self.delay)
        except asyncio.TimeoutError:
            self.callback_started = True

            return await maybe_awaitable(self.callback, *(self.args or ()), **(self.kw or {}))

        finally:
            if self.on_finished is not None:
                await maybe_awaitable(self.on_finished, self)

        return None

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

        During the delay this always keeps the callback from starting. Once
        it has started, it is cancelled only with `force`. `callback_started`
        is set just before the callback is awaited, so a narrow window exists
        where a non-forced cancel lets a callback that has not run a line yet
        go ahead.

        Args:
            force: Cancel the callback even if it has already started.
        """
        task = self._task

        if task is None:
            return

        self.cancel_event.set()

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
