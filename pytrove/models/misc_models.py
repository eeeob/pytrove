from typing import Generic, Tuple, Mapping, Optional, Any, Union, Dict

try:
    from typing import Self
except ImportError:  # Python < 3.11
    from typing_extensions import Self

from dataclasses import field, dataclass
from threading import RLock
from concurrent.futures import ThreadPoolExecutor

from ..typings import (
    MaybeAwaitable, Number,
    MaybeCoroutineCallable, PathLike,
    _T, _KT, _VT
)
from ..enums import TriggerOn


from ..validate_tools import is_exception
from ..async_tools import maybe_awaitable, to_thread, safe_wait_task
from ..files_tools import read_json, write_json
from ..num_tools import _tri_cdf, _tri_icdf

from .base import BaseDataClass

import asyncio
import random

_NOT_SET = object()

_INV_PHI = 0.6180339887498949   # (5 ** 0.5 - 1) / 2 -- the golden-ratio step


@dataclass(slots=True)
class DeferredCall(Generic[_T]):
    func: MaybeAwaitable[..., _T]
    args: Optional[Tuple] = None
    kw: Optional[Mapping] = None

    when: TriggerOn = TriggerOn.SUCCESS
    

    def should_run(self, r: Any) -> bool:
        when = self.when

        return (
            when == TriggerOn.ALWAYS or
            (is_exception(r) and when == TriggerOn.ERROR) or
            (not is_exception(r) and when == TriggerOn.SUCCESS)
            
        )

    async def run(self, *args: Any, executor: Optional[ThreadPoolExecutor] = None, **kw: Any) -> _T:
        """Run `func` -- `args`/`kw` given here are appended to/merged over
        whatever was set on the instance at construction, so a one-off extra
        argument does not need a new DeferredCall just to carry it.

        A keyword given both at construction and here is overridden by the
        one given here; positional args here are appended after the stored
        ones, the same order `func` would see them written out by hand.
        """

        call_args = (*(self.args or ()), *args)
        call_kw = {**(self.kw or {}), **kw}

        return await maybe_awaitable(
            self.func,
            *call_args, **call_kw,
            executor=executor
        )

@dataclass(slots=True)
class JsonContainer(Generic[_KT, _VT], BaseDataClass):
    path: PathLike
    lock: Optional[RLock] = None

    data: Dict[_KT, _VT] = field(default=_NOT_SET, init=False)

    def is_loaded(self) -> bool:
        return self.data is not _NOT_SET

    def unload(self) -> None:
        self.data = _NOT_SET

    def load(self, **kw) -> None:
        if not self.is_loaded():
            self.data = read_json(self.path, lock=self.lock, **kw)

    def save(self, **kw) -> None:
        if not self.is_loaded():
            raise RuntimeError("JsonContainer has no data loaded to save")

        write_json(
            self.path, 
            self.data, 
            self.lock, 
            **kw
        )
    
    def get(self, key: _KT, default: Optional[_T] = None) -> Optional[Union[_VT, _T]]:
        self.load()
        return self.data.get(key, default)
    
    def set(self, key: _KT, value: _VT, save_now: bool = False) -> None:
        self.load()

        self.data[key] = value

        if save_now:
            self.save()

    def delete(self, key: _KT, save_now: bool = False) -> None:
        self.load()

        if self.data.pop(key, None) is not None:
            if save_now:
                self.save()
    
    def update(self, update: Dict[_KT, _VT], save_now: bool = False) -> None:
        self.load()

        self.data.update(update)

        if save_now:
            self.save()

    async def async_load(self, **kw) -> None:
        await to_thread(self.load, **kw)
    
    async def async_save(self, **kw) -> None:
        await to_thread(self.save, **kw)
    
    async def async_get(self, key: _KT, default: Optional[_T] = None) -> Optional[Union[_VT, _T]]:
        if not self.is_loaded():
            await self.async_load()
        return self.data.get(key, default)

    async def async_set(self, key: _KT, value: _VT, save_now: bool = False) -> None:
        if not self.is_loaded():
            await self.async_load()

        self.data[key] = value

        if save_now:
            await self.async_save()

    async def async_delete(self, key: _KT, save_now: bool = False) -> None:
        if not self.is_loaded():
            await self.async_load()

        if self.data.pop(key, None) is not None:

            if save_now:
                await self.async_save()

    async def async_update(self, update: Dict[_KT, _VT], save_now: bool = False) -> None:
        if not self.is_loaded():
            await self.async_load()

        self.data.update(update)
        
        if save_now:
            await self.async_save()


@dataclass(slots=True)
class DelayedCallback(Generic[_T]):
    delay: Number
    callback: MaybeAwaitable[..., _T]

    args: Optional[Tuple[Any, ...]] = None
    kw: Optional[Mapping[str, Any]] = None

    on_finished: Optional[MaybeCoroutineCallable[[Self], Any]] = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    callback_started: bool = field(default=False, init=False)
    _task: Optional[asyncio.Task[Optional[_T]]] = field(
        default=None, 
        init=False, 
        repr=False, 
    )

    
    async def wait(self) -> Optional[_T]:
        """Wait out `delay`, then run `callback` -- unless cancel() sets
        `cancel_event` first, in which case the callback never runs at all.

        The control flow here is inverted from what the names suggest:
        waiting for `cancel_event` to fire is the thing being awaited, and
        *timing out* on that wait -- i.e. `cancel_event` was never set within
        `delay` -- is the success path that goes on to run the callback.
        `cancel_event` actually firing means "cancelled", and simply lets the
        `wait_for` return normally with no TimeoutError, skipping the
        callback entirely.
        """

        try:
            await asyncio.wait_for(self.cancel_event.wait(), timeout=self.delay)
        except asyncio.TimeoutError:
            self.callback_started = True

            return await maybe_awaitable(
                self.callback,
                *(self.args or ()),
                **(self.kw or {})
            )

        finally:
            if self.on_finished is not None:
                await maybe_awaitable(self.on_finished, self)

    def start(self) -> asyncio.Task[Optional[_T]]:
        if self._task is None:
            self._task = asyncio.create_task(self.wait())

        return self._task

    async def cancel(self, force: bool = False) -> None:
        """Stop this DelayedCallback: during the delay this always prevents
        the callback from ever starting; once the callback has *started*
        running, `force=False` (the default) lets it finish undisturbed and
        only `force=True` actually cancels the in-flight task.

        `callback_started` is set the instant `wait_for` times out, before
        `callback` itself is awaited -- so there is a real (if narrow) window
        where cancel() has already observed `callback_started=True` and will
        skip task.cancel() even though the callback hasn't executed a single
        line yet.
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
    def task(self) -> Optional[asyncio.Task[Optional[_T]]]:
        return self._task

    @property
    def started(self) -> bool:
        return self._task is not None

    @property
    def done(self) -> bool:
        return self._task is not None and self._task.done()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()


@dataclass(slots=True, eq=False)
class Jitter:
    """A stream of random values around `value` that spread across the
    window instead of piling up near its peak.

        j = Jitter(5)                       # +/-10% of 5, i.e. ~[4.5, 5.5]
        j = Jitter(5, decrease=0.2, increase=0.5)   # ~[4.0, 7.5]
        [j() for _ in range(50)]            # no run of near-equal values

    The window is ``[value*(1 - decrease), value*(1 + increase)]`` and the
    shape across it is triangular, peaking `bias` of the way from the low
    end to the high one -- ``0.5`` (default) a symmetric peak, ``1.0`` all
    the mass against the high end (favouring the full `increase`), ``0.0``
    against the low end; outside ``[0, 1]`` is clamped. `decrease` and
    `increase` default to ``0.1`` each, so a bare ``Jitter(x)`` is a modest
    +/-10% around `x`.

    Drawing ``jitter(...)`` independently in a loop keeps landing near the
    peak -- that is the distribution, not a bug. This instead walks the
    window with a golden-ratio (low-discrepancy) step in CDF space: every
    call lands a long way -- in probability -- from the one before, so the
    sequence covers the whole window while each value is still random and
    the triangular shape (hence `bias`) still holds over a run. Consecutive
    values cannot cluster; that is a property of the step, not a filter on
    top of it.

    `wobble` (0..1, default 1) is how much random noise rides on that step:
    ``0`` is the rigid golden walk (spread but predictable), ``1`` is as
    loose as it gets while the no-cluster guarantee still holds.

    `min_distance` is a hard floor on top of the walk: when a step lands
    within it of `last`, the value is snapped just past the near edge of
    that band (with a small nudge that keeps it near the edge, so a low or
    high `bias` is not dragged across the window by the correction) and the
    walk is resynced there. As long as the window is at least `min_distance`
    wide the floor always holds; past that it returns the furthest reachable
    end.

    Every field is a plain attribute -- reassign `value` between calls to
    walk the window around. `last` is the most recent value (None until the
    first call); `reset()` restarts the walk from a fresh random phase.
    Pass `rng` (any ``random.Random``) for a reproducible stream.
    """

    value: float
    decrease: float = 0.1
    increase: float = 0.1
    bias: float = 0.5
    wobble: float = 1.0
    min_distance: float = 0.0
    rng: Optional[random.Random] = None

    last: Optional[float] = field(default=None, init=False)
    _u: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._u = (self.rng or random).random()   # random phase, so two Jitters differ

    def __call__(self) -> float:
        src = self.rng or random

        low = self.value * (1.0 - self.decrease)
        high = self.value * (1.0 + self.increase)

        if low > high:
            low, high = high, low

        if high <= low:
            self.last = low
            return low

        bias = self.bias
        if bias < 0.0:
            bias = 0.0
        elif bias > 1.0:
            bias = 1.0

        mode = low + (high - low) * bias

        wobble = self.wobble
        if wobble < 0.0:
            wobble = 0.0
        elif wobble > 1.0:
            wobble = 1.0

        # Golden-ratio (Kronecker) recurrence in CDF space. A fixed step of
        # phi^-1 puts every consecutive pair ~0.382 apart on the wrapped
        # unit circle (three-distance theorem); the noise below is capped so
        # the step stays inside ~[0.44, 0.79] and that wrapped gap never
        # falls under ~0.2 -- i.e. two draws in a row can still not cluster.
        step = _INV_PHI
        if wobble:
            noise = _INV_PHI * 0.28 * wobble
            step += src.uniform(-noise, noise)

        self._u = (self._u + step) % 1.0
        result = _tri_icdf(self._u, low, high, mode)

        gap = self.min_distance

        if gap > 0.0 and self.last is not None and abs(result - self.last) < gap:
            # The step landed inside `last +/- gap`. Snap out to the near
            # edge of that band, not by resampling the far side of the
            # window -- that reaches deep into the opposite tail and washes
            # `bias` out. The `** 3` keeps the nudge hugging the edge.
            # Follow the direction the step leaned; flip if that edge is
            # outside the window; take the furthest end if neither fits.
            up = self.last + gap
            down = self.last - gap

            if up <= high and (result >= self.last or down < low):
                result = up + (high - up) * (src.random() ** 3)
            elif down >= low:
                result = down - (down - low) * (src.random() ** 3)
            else:
                result = low if (self.last - low) >= (high - self.last) else high

            # Resync the walk so the next step measures its ~0.38 in CDF
            # space from where the value actually landed.
            self._u = _tri_cdf(result, low, high, mode)

        self.last = result
        return result

    next = __call__

    def reset(self) -> None:
        self.last = None
        self._u = (self.rng or random).random()


__all__ = (
    "DeferredCall",
    "JsonContainer",
    "DelayedCallback",
    "Jitter",

)