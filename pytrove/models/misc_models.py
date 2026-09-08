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

from .base import BaseDataClass

import asyncio

_NOT_SET = object()


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


__all__ = (
    "DeferredCall", 
    "JsonContainer", 
    "DelayedCallback", 

)