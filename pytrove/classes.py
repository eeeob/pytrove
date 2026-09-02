from typing import (
    Any, Awaitable, Callable, TYPE_CHECKING,
    Dict, Optional, Generic, Set,
    overload, Type, Hashable, ClassVar, TypeVar
)

try:
    from typing import Self
except ImportError:  # Python < 3.11
    from typing_extensions import Self

import sys

if sys.version_info < (3, 13):
    from typing_extensions import TypeVar

from abc import ABC
from types import MethodType
from functools import partial, cached_property
from datetime import datetime, timezone, timedelta

try:
    from pymongo import IndexModel
except ImportError:
    HAS_PYMONGO = False
else:
    HAS_PYMONGO = True

try:
    import wrapt
except ImportError:
    HAS_WRAPT = False
else:
    HAS_WRAPT = True

from ._optional import _unavailable_class

from .typings import _KT, _VT, _T, _P, Number, MaybeContainer
from .async_tools import to_thread
from .callable_tools import run_awaitable_in_coro, safe_call, ignore_arguments
from .iter_tools import to_frozenset

import weakref
import logging
import threading
import asyncio
import time
import warnings
import inspect

log = logging.getLogger(__name__)


class classproperty(Generic[_T, _VT]):
    """Like @property, but the getter receives the class instead of an
    instance, and works when accessed on the class itself (`Cls.attr`, not
    just `Cls().attr`).

    Can be used bare (`@classproperty`) or called with kwargs first
    (`@classproperty(cached=True)`) -- __new__ tells the two apart by
    whether `fget` was passed positionally: no `fget` means it was invoked
    as `classproperty(...)`, so a `functools.partial` standing in for the
    decorator is returned instead of an instance, to be called again once
    the actual getter function is available.

    `cached=True` memoizes the getter's return value per owning class in
    `_cache`, keyed by the class itself -- so a subclass gets its own cached
    computation rather than inheriting the base class's cached value.
    """

    __slots__ = "call", "doc"

    @overload
    def __new__(
        cls,
        fget: Callable[[Type[_T]], _VT],
        *,
        doc: Optional[str] = None,
        cached: bool = False
    ) -> "classproperty[_T, _VT]": ...
    @overload
    def __new__(
        cls,
        fget: None = None,
        *,
        doc: Optional[str] = None, 
        cached: bool = False 
    ) -> Callable[
        [Callable[[Type[_T]], _VT]], "classproperty[_T, _VT]"
        ]: ...
    def __new__(cls, fget = None, *, doc = None, cached = False): 
        if fget is None:
            return partial(cls, doc=doc, cached=cached)

        return super().__new__(cls)

    def __init__(
        self, 
        fget: Callable[[Type[_T]], _VT], 
        *, 
        doc: Optional[str] = None, 
        cached: bool = False 
    ) -> None:
        
        self.call = KeyDefaultWeakKeyDict(fget) if cached else fget
        self.doc = fget.__doc__ if doc is None else doc

    @property
    def __doc__(self) -> str:
        return self.doc

    @overload
    def __get__(self, _: Any, owner: None) -> Self: ...
    @overload
    def __get__(self, _: Any, owner: Type[_T]) -> _VT: ...
    def __get__(self, _, owner):
        if owner is None:
            return self

        value = self.call(owner)
        
        try:
            return value
        finally:
            if value is self and isinstance(self.call, KeyDefaultWeakKeyDict):
                self.call.pop(owner, None)



if TYPE_CHECKING:
    # Type checkers see hybridmethod as classmethod so `self`/`cls`-typed
    # first parameters are checked normally; the real runtime behavior below
    # (receiving the instance when called on one) isn't expressible in the
    # stdlib typing vocabulary.
    hybridmethod = classmethod
else:
    class hybridmethod(classmethod):
        """A method callable as either `Cls.method()` (receives the class,
        like classmethod) or `instance.method()` (receives the instance
        instead, like a normal method) -- the same function body serves both,
        branching on which one was used to look it up.

        Subclassing classmethod reuses its __init__/attribute storage; only
        __get__ (the descriptor protocol hook that runs on attribute access)
        is overridden, substituting `instance` for `owner` whenever an
        instance is actually available.
        """

        def __get__(self, instance, owner = None, /):
            if instance is not None:
                owner = instance

            return MethodType(self.__func__, owner)

class FrozenClassAttrs:
    def __setattr__(self, name, value):
        if hasattr(self.__class__, name):
            raise AttributeError(
                f"Cannot override class attribute '{name}' from instance"
            )
        super().__setattr__(name, value) 
 
class KeyDefaultDict(Dict[_KT, _VT]):
    def __init__(self, default_factory: Callable[[_KT], _VT]) -> None:
        super().__init__()
        self.default_factory = default_factory

    def __missing__(self, key: _KT) -> _VT:
        value = self.default_factory(key)
        self[key] = value
        return value
    
    def __call__(self, key: _KT) -> _VT:
        return self[key]

if HAS_WRAPT:
    class RestrictedProxy(wrapt.ObjectProxy):
        """A proxy that restricts access to named attributes on the wrapped object.

        The wrapped object is exposed through `wrapt.ObjectProxy`, but attribute
        reads and writes are filtered by either a deny-list (`blocked`) or an
        allow-list (`allowed`). Passing both at once raises `ValueError`.

        The internal proxy state uses the `'_self_'` namespace reserved by
        `wrapt`, so `_self_blocked` and `_self_allowed` are stored without being
        intercepted by the restriction checks.
        """

        def __init__(
            self,
            obj: Any,
            blocked: Optional["MaybeContainer[str]"] = None,
            allowed: Optional["MaybeContainer[str]"] = None,
            ):

            blocked = to_frozenset(blocked)
            allowed = to_frozenset(allowed)

            if blocked and allowed:
                raise ValueError("blocked and allowed cannot both be provided")

            super().__init__(obj)

            self._self_blocked = blocked
            self._self_allowed = allowed or None

        def _check(self, name):
            if self._self_allowed is not None:
                if name not in self._self_allowed:
                    raise AttributeError(f"Attribute '{name}' is not allowed")
            elif name in self._self_blocked:
                raise AttributeError(f"Attribute '{name}' is blocked")

        def __getattr__(self, name):
            self._check(name)
            return super().__getattr__(name)

        def __setattr__(self, name, value):
            if not name.startswith('_self_'):
                self._check(name)
            super().__setattr__(name, value)

    class WeakRestrictedProxy(RestrictedProxy):
        """A transparent proxy that hands out an object without handing out full
        control of it: named attributes raise AttributeError instead of resolving,
        and the reference held is weak, so the proxy never keeps the target alive.

        Pass either `blocked` (deny-list -- everything else passes) or `allowed`
        (allow-list -- everything else is denied), never both. `callback` is
        forwarded to weakref.proxy() and fires when the target is collected.

        Built on wrapt.ObjectProxy rather than a hand-written __getattr__ shim
        because ObjectProxy also forwards dunders, `isinstance`, and the operator
        protocols -- a plain shim would silently fail on all of those. wrapt
        reserves the `_self_` prefix for the proxy's own state, which is why the
        two attributes below are named that way and why __setattr__ lets that
        prefix through unchecked.
        """

        def __init__(
                self,
                obj: _T,
                blocked: Optional["MaybeContainer[str]"] = None,
                allowed: Optional["MaybeContainer[str]"] = None,
                callback: Optional[Callable[[_T], Any]] = None
            ):
            super().__init__(
                weakref.proxy(obj, callback),
                blocked,
                allowed,
                )
else:
    RestrictedProxy = _unavailable_class("RestrictedProxy", ("wrapt", "proxy"))
    WeakRestrictedProxy = _unavailable_class("WeakRestrictedProxy", ("wrapt", "proxy"))

class AioThreadWorker:
    """Runs coroutine functions on a private event loop in its own thread.

    Every submission goes straight onto that loop via
    asyncio.run_coroutine_threadsafe(), so submit() is safe to await from any
    thread -- including threads with no event loop of their own. It is itself a
    coroutine function: awaiting it resumes on the caller's own loop with the
    work's result, and cancelling that await cancels the work on the worker's
    loop too.

    A worker owns exactly one thread for its whole lifetime: once that thread
    ends the worker is finished for good and a new instance is needed.

    `concurrency` caps how many submissions execute at once (0 or less means
    unlimited). Note that submissions above the cap are already live tasks
    parked on a semaphore inside the loop, not entries in an external queue.
    Under a cap, submitted work must not await submit() on the same worker: the
    outer task holds a slot the inner one waits for, so both hang and join()
    never drains.

    Concurrency contract
    --------------------
    `__lock` guards only the lifecycle transitions -- publishing `__thread` in
    run(), and flipping `__stopping` in join(). Everything else is deliberately
    lock-free and relies on three properties instead:

    - **Monotonic state.** `__thread` is assigned exactly once and never reset,
      `__stopping` only ever goes False->True, and `__running` is set once and
      cleared once. So a check that passes can only become stale in one
      direction, which is the direction each caller already handles.
    - **Publication order.** `__worker` assigns `__loop` *before* setting
      `__running`, and teardown clears `__running` *before* nulling `__loop`.
      A reader that sees `__running` set therefore always sees a real `__loop`.
    - **Re-validation at the point of use.** submit() checks state on entry and
      then again, right before scheduling, via get_loop() -- which re-tests the
      worker *and* the loop's own is_running()/is_closed(). The entry check is
      only a fast path; get_loop() is what actually makes it safe, and is why
      submit() needs no lock (and stays correct under `python -O`, where its
      entry asserts are stripped).

    A submission that loses the race against join() is reported to its caller
    as RuntimeError -- never silently dropped, and never left hanging.
    """

    def __init__(
        self,
        name: Optional[str] = None,
        concurrency: int = 0,
        loop_factory = None,
        exception_handler = None,
        run_now: bool = True,
        ):

        # bool passes this check and is accepted on purpose: True then reads as
        # a cap of 1 and False as unlimited.
        if not isinstance(concurrency, int):
            raise TypeError(
                f"concurrency must be an int, got {type(concurrency).__name__!r}"
            )

        if loop_factory is not None and not callable(loop_factory):
            raise TypeError(
                f"loop_factory must be callable, got {type(loop_factory).__name__!r}"
            )

        if exception_handler is not None and not callable(exception_handler):
            raise TypeError(
                f"exception_handler must be callable, "
                f"got {type(exception_handler).__name__!r}"
            )

        # asyncio.run() only gained loop_factory in 3.12, not 3.11.
        if sys.version_info < (3, 12) and loop_factory is not None:
            warnings.warn(
                "loop_factory is ignored on Python < 3.12 "
                "(asyncio.run() has no loop_factory parameter there); "
                "falling back to a plain asyncio.run()",
                stacklevel=2,
            )

        self.__name = name
        self.__concurrency = concurrency
        self.__loop_factory = loop_factory
        self.__exception_handler = exception_handler

        # Guards only the lifecycle transitions: publishing __thread in run()
        # and flipping __stopping in join(). See the class docstring for why
        # submit() deliberately takes no lock.
        self.__lock = threading.RLock()
        # Set once __worker has published __loop and is ready for submissions;
        # cleared once during teardown.
        self.__running = threading.Event()

        # Created in run(), not here, so nothing is spawned until the worker is
        # actually started. Assigned exactly once and never reset to None.
        self.__thread: Optional[threading.Thread] = None
        self.__loop: Optional[asyncio.AbstractEventLoop] = None

        # All three are asyncio primitives bound to the worker's own loop, so
        # they are built inside __worker() and only touched from that loop.
        self.__tasks: Optional[Set["asyncio.Task[Any]"]] = None
        self.__slots: Optional[asyncio.Semaphore] = None
        self.__drain: Optional[asyncio.Event] = None

        # Only ever goes False -> True, which is what makes the lock-free
        # is_stopping() checks elsewhere safe to act on.
        self.__stopping: bool = False
        # Filled by run()'s safe_call handler if the worker thread dies, so
        # wait_for_running() can surface the real cause instead of a bare
        # "thread ended".
        self.__thread_exc: Optional[BaseException] = None

        if run_now:
            self.run()

    @cached_property
    def __loop_proxy(self) -> WeakRestrictedProxy:
        """The loop as handed to callers of get_loop(): usable for scheduling,
        but with close()/stop() denied.

        The worker owns its loop's lifecycle -- asyncio.run() inside
        __bootstrap starts and tears it down. Letting a caller stop or close it
        would skip that path entirely: __worker would never return from
        __drain.wait(), in-flight tasks would be abandoned, and the worker would
        keep reporting itself as running. Blocking the two methods makes that
        unreachable rather than merely discouraged.

        Cached because the proxy is immutable and the loop is assigned once;
        weak, so holding the proxy never keeps a dead loop alive.
        """

        if self.__loop is None:
            raise RuntimeError(
                "the worker's event loop has not been published yet -- the "
                "loop is only created once the worker thread reaches __worker(); "
                "use get_loop(), which waits on that, instead of touching this"
            )

        return WeakRestrictedProxy(self.__loop, blocked=["close", "stop"])

    def __bootstrap(self) -> None:
        """Thread entry point: own the loop for the worker's whole lifetime.

        Runs on the worker thread only; run() hands it to safe_call() so a
        crash lands in __thread_exc instead of just threading.excepthook.
        """

        # run() starts the thread and only then assigns __thread, so this
        # thread can arrive before the assignment lands. Waiting for it is what
        # makes the identity check below meaningful -- reading __thread too
        # early would see None and reject a perfectly valid worker thread.
        while self.__thread is None:
            time.sleep(0.005)

        if threading.current_thread() is not self.__thread:
            raise RuntimeError("Bootstrap must be called from the worker thread")

        loop_factory = self.__loop_factory
        del self.__loop_factory
        # Built before the try so a loop_factory that blows up cannot leave
        # asyncio.run() half-entered with the coroutine already created.
        coro = self.__worker()

        try:
            if sys.version_info < (3, 12):
                asyncio.run(coro)
            else:
                asyncio.run(coro, loop_factory=loop_factory)
        finally:
            # Order matters and mirrors __worker's publication order in
            # reverse: __running is cleared FIRST, so any reader that still
            # sees it set is guaranteed a non-None __loop below it.
            self.__running.clear()

            self.__tasks = None
            self.__slots = None
            self.__drain = None
            self.__loop = None


    async def __worker(self) -> None:
        """The single task asyncio.run() drives: set the loop up, park until
        join() asks to stop, then drain every submission before returning.

        Returning from here is what lets asyncio.run() tear the loop down, so
        this coroutine's lifetime *is* the worker's lifetime.
        """

        loop = asyncio.get_running_loop()

        exception_handler = self.__exception_handler

        if exception_handler is not None:
            loop.set_exception_handler(exception_handler)

        del self.__exception_handler, exception_handler

        # asyncio primitives bind to whichever loop first uses them, so they
        # must be constructed here, on the worker's own loop, and never in
        # __init__ (which runs on the caller's thread).
        self.__tasks = set()
        self.__drain = asyncio.Event()
        self.__slots = (
            asyncio.Semaphore(self.__concurrency)
            if self.__concurrency > 0
            else None
        )

        del self.__concurrency

        # Publication order, relied on by get_loop() and by teardown: __loop is
        # assigned BEFORE __running is set, so anyone who observes __running
        # necessarily observes a usable __loop too.
        self.__loop = loop
        self.__running.set()

        await self.__drain.wait()

        # Everything submitted is tracked in __tasks -- including tasks still
        # parked on the semaphore -- so gathering until the set is empty drains
        # all of it. Looped rather than gathered once because a task scheduled
        # just before the drain began can register itself in __tasks while an
        # earlier gather() is already running.
        while self.__tasks:
            await asyncio.gather(*self.__tasks, return_exceptions=True)
        
    

    # ---------------- state ----------------

    def is_started(self) -> bool:
        """Whether run() has ever spawned the thread. Never goes back to False."""
        return self.__thread is not None

    def is_running(self) -> bool:
        """Whether the worker is up and able to accept work right now.

        Deliberately stricter than `is_started() and not is_finished()`: the
        thread being alive is not enough, since it is alive throughout startup
        before __worker has published the loop. Only __running being set means
        submissions can actually be scheduled.
        """

        thread = self.__thread

        return (
            thread is not None
            and thread.is_alive()
            and self.__running.is_set()
        )

    def is_stopping(self) -> bool:
        """Whether join() has asked the worker to stop. Never goes back to False."""
        return self.__stopping

    def is_finished(self) -> bool:
        """Whether the worker's single thread has run and ended for good.

        Keyed on the thread being dead rather than on `not is_running()`, which
        would also be true during startup and would wrongly report a worker
        that is still coming up as finished.
        """

        return self.is_started() and not self.__thread.is_alive()

    def get_loop(self) -> asyncio.AbstractEventLoop:
        """Return the worker's loop, wrapped so its lifecycle cannot be driven
        from outside (see __loop_proxy).

        This is also submit()'s second, authoritative gate: it re-checks the
        worker *and* asks the loop itself whether it is still running and open,
        immediately before anything is scheduled on it. That re-validation is
        what closes the window between submit()'s lock-free entry check and the
        actual hand-off, so a worker torn down mid-submit surfaces a clear
        RuntimeError instead of a hang or an error from deep inside asyncio.
        """

        loop = self.__loop

        if loop is None or not self.is_running():
            raise RuntimeError("Worker not running")

        if not loop.is_running():
            raise RuntimeError(
                "the worker's event loop is not running -- the worker thread is "
                "alive but its loop has already left run_forever(), so nothing "
                "scheduled on it would ever execute"
            )

        if loop.is_closed():
            raise RuntimeError(
                "the worker's event loop is already closed -- the worker is "
                "past teardown and cannot accept any further work"
            )

        return self.__loop_proxy

    # ---------------- lifecycle ----------------

    def run(self, wait: Optional[Number] = None) -> None:
        """Start the worker thread. Idempotent while the worker is alive.

        Returns as soon as the thread is spawned; pass `wait` (seconds) to
        block until the worker is actually able to accept work. Without it the
        worker may legitimately still be starting when this returns.

        Calling run() again on a live worker is a no-op rather than an error,
        so concurrent callers racing to start the same worker all succeed and
        exactly one thread is created -- the whole start sequence is under
        __lock, so a loser sees is_started() already True.
        """

        def _exc_thread_handler(exc: BaseException):
            # Captured so wait_for_running()/join() can name the real cause
            # instead of only reporting that the thread is gone.
            self.__thread_exc = exc
            log.error("AioThreadWorker thread died", exc_info=exc)

        with self.__lock:
            if not self.is_started():
                if self.is_stopping():
                    raise RuntimeError(
                        "worker has already been asked to stop and cannot be "
                        "started; create a new AioThreadWorker instead"
                    )

                
                thread = threading.Thread(
                    target=safe_call, 
                    args=(self.__bootstrap, ), 
                    kwargs={"log_exc": _exc_thread_handler}, 
                    name=self.__name,
                    daemon=True,
                )

                # __thread is published after start(); __bootstrap waits for
                # that assignment rather than racing it (see its comment).
                thread.start()
                self.__thread = thread

                del self.__name
            elif not self.__thread.is_alive():
                raise RuntimeError(
                    "worker is finished -- a worker owns a single thread for "
                    "its whole lifetime and cannot be restarted; create a new "
                    "AioThreadWorker instead"
                )


        if wait is not None:
            self.wait_for_running(wait)

    def wait_for_running(self, timeout: Optional[Number] = None) -> None:
        """Block until the worker can accept work, or raise explaining why it
        never will. Returns immediately if it is already running.

        Blocking, so never call it from inside an event loop -- join() reaches
        it through to_thread() for exactly that reason.
        """

        if not self.is_started():
            raise RuntimeError(
                "worker has not been started -- call run() first (or construct "
                "with run_now=True); there is no thread to wait on yet"
            )

        if self.is_running():
            return

        thread = self.__thread

        if threading.current_thread() is thread:
            raise RuntimeError(
                "cannot wait for the worker to start from inside the worker's "
                "own thread -- it is the thread that would have to make "
                "progress, so this would block forever"
            )

        deadline = None if timeout is None else time.monotonic() + timeout

        # Polled rather than one blocking Event.wait(timeout) so a thread that
        # dies during startup is reported promptly instead of stalling the
        # caller until the timeout (or forever, when timeout is None).
        while not self.__running.wait(0.005):
            if not thread.is_alive():
                raise RuntimeError(
                    "worker thread ended before it ever started running"
                ) from self.__thread_exc

            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    f"worker did not start running within {timeout!r} seconds"
                )

    async def join(self, timeout: Optional[Number] = None, ) -> None:
        """Stop the worker and wait for it: refuse new submissions, let every
        in-flight one finish, then wait for the thread to end.

        `timeout` bounds only the final wait for the thread, not the whole
        call -- a worker still starting up is waited for unconditionally first,
        since there is no loop to signal until it has one.

        Safe to call concurrently and repeatedly: the first caller flips
        __stopping under __lock and is the only one that signals the drain;
        the rest fall straight through to waiting on the thread.

        Calling it on a never-started worker still marks it stopping, which
        permanently prevents run() from starting it -- join() means "this
        worker is done", not "stop it if it happens to be running".
        """

        if threading.current_thread() is self.__thread:
            raise RuntimeError(
                "cannot join from inside the worker's own thread -- the "
                "calling task is itself in-flight work, so waiting for the "
                "worker to drain here would deadlock"
            )

        with self.__lock:
            was_stopping = self.is_stopping()

            if not was_stopping:
                self.__stopping = True

        if not self.is_started():
            return

        if not was_stopping:
            # Wait for startup before signalling: __drain and __loop only exist
            # once __worker has built them, and this is the one caller that
            # must reach the drain-set below. wait_for_running() can only fail
            # if the thread is already dead, so the flag can never be left set
            # with the drain unsignalled on a live worker.
            await to_thread(self.wait_for_running)

            # Hand the signal to the worker's own loop rather than setting the
            # asyncio.Event directly -- Event is not thread-safe.
            self.__loop.call_soon_threadsafe(self.__drain.set)

        thread = self.__thread

        if not thread.is_alive():
            return

        # __worker drains its own tasks before returning, so waiting on the
        # thread covers both the drain and asyncio.run()'s loop teardown.
        await to_thread(thread.join, timeout)

        if timeout is not None and thread.is_alive():
            raise TimeoutError(
                f"worker did not stop within {timeout!r} seconds"
            )

    def __await__(self):
        return self.join().__await__()

    # ---------------- submission ----------------
    
    async def submit(
        self,
        func: Callable[_P, Awaitable[_T]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
        ) -> _T:

        """Run `func(*args, **kwargs)` on the worker's loop and await its result.

        `func` must be an awaitable function. It is *called* on the worker's
        loop, not here, so it may freely touch the running loop; this call
        itself is awaitable from any thread and any loop -- including a thread
        with no loop of its own, since the hand-off goes through
        run_coroutine_threadsafe().

        Cancelling this await cancels the work on the worker's loop too. A
        CancelledError that came from the worker shutting down rather than from
        the caller is re-reported as RuntimeError, so shutdown never looks like
        the caller's own cancellation.
        """

        async def run_task():
            """Wrapper every submission actually runs as, on the worker's loop.
    
            Takes a factory rather than a ready awaitable so `func(*args)` is
            called here, on the worker's loop -- a coroutine function that touches
            the running loop while being *called* would otherwise bind to the
            submitting thread's loop, or fail outright if that thread has none.
            """
    
            awaitable = func(*args, **kwargs)
    
            if not inspect.isawaitable(awaitable):
                raise TypeError(
                    f"func must be a awaitable function; calling it returned "
                    f"{type(awaitable).__name__!r}"
                )
    
            task = asyncio.current_task()
    
            # Captured once: teardown nulls these, and a task scheduled just before
            # that must still untrack itself from the very set it registered in.
            tasks = self.__tasks
            slots = self.__slots
    
            # Registered before awaiting anything, so join()'s drain loop sees this
            # task even while it is only parked on the semaphore below.
            if tasks is not None:
                tasks.add(task)
    
            try:
                if slots is None:
                    return await awaitable
    
                # A semaphore rather than a counter/condition pair: release() is
                # synchronous, so the slot is returned even while the task is being
                # cancelled -- an awaited release could itself be interrupted and
                # leak the slot permanently.
                await slots.acquire()
    
                try:
                    return await awaitable
                finally:
                    slots.release()
            finally:
                if tasks is not None:
                    tasks.discard(task)

        # Fast path only -- deliberately lock-free, and stripped entirely under
        # `python -O`. get_loop() inside coro() is the check that actually
        # matters; see the class docstring.
        try:
            assert self.is_running(), "worker is closed"
            assert not self.is_stopping(), "worker is stopping"
        except AssertionError as m:
            raise RuntimeError(str(m)) from None

        async def coro():
            # Re-validated here, immediately before the hand-off: this is the
            # narrow point where a concurrent join() would otherwise let work
            # be scheduled onto a loop that is already tearing down.
            current_loop = asyncio.get_running_loop()
            loop = self.get_loop()

            if current_loop == loop:
                return await run_task()

            return await asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(run_task(), loop)
            )

        try:
            return await coro()
        except asyncio.CancelledError:
            # cancelling() (3.11+) counts cancellations requested against *this*
            # task, so zero means our caller never asked -- the CancelledError
            # can only have come from the worker's teardown cancelling the
            # submitted task. Left as CancelledError it would silently mark the
            # caller's own task cancelled instead of explaining what happened.
            cancelling = getattr(asyncio.current_task(), "cancelling", None)

            if cancelling is not None and cancelling() == 0 and (self.is_stopping() or not self.is_running()):
                raise RuntimeError(
                    "AioThreadWorker stopped before this task completed"
                ) from None

            raise
        

    __call__ = submit


    async def __aenter__(self) -> Self:
        self.run()
        self.wait_for_running()
        return self

    async def __aexit__(self, *_) -> None:
        await self.join()


if HAS_PYMONGO:
    class MongoIndex(IndexModel):
        @classmethod
        def from_dict(cls, dct: Dict[str, Any]):
            dct.pop("v", None)
            dct.pop("name", None)

            return cls(dct.pop("key"), **dct)
        
        @property
        def name(self):
            return self.document["name"]
        
        @property
        def key(self):
            return "_".join(self.document["key"].keys())

        def __hash__(self):
            return hash(repr(self))
        
        def __eq__(self, other):
            if not isinstance(other, MongoIndex):
                raise NotImplementedError
            return repr(self) == repr(other)
else:
    MongoIndex = _unavailable_class("MongoIndex", ("pymongo", "mongo"))


class KeyDefaultWeakValueDict(weakref.WeakValueDictionary[_KT, _VT]):
    def __init__(self, default_factory: Callable[[_KT], _VT]) -> None:
        if not callable(default_factory):
            raise TypeError("default_factory must be callable")
        
        super().__init__()

        self.default_factory = default_factory

    def __getitem__(self, key: _KT) -> _VT:
        try:
            return super().__getitem__(key)
        except KeyError:
            value = self.default_factory(key)
            self[key] = value
            return value
    
    __call__ = __getitem__

class DefaultWeakValueDict(KeyDefaultWeakValueDict[_KT, _VT]):
    """KeyDefaultWeakValueDict whose factory is called with no arguments.

    The key is what the parent hands its factory; this is for the common case
    where the default does not depend on it. Wrapped with callable_tools'
    ignore_arguments, whose functools.wraps leaves `__wrapped__` pointing at
    the original -- that is what makes the unwrap below possible.
    """

    def __init__(self, default_factory: Callable[[], _VT]) -> None:
        # Unwrap first: this may be one of our own ignore_arguments adapters
        # coming back, from a caller rebuilding the mapping out of
        # `default_factory`. Wrapping it again would call the unwrapped
        # factory with no arguments through a second layer that also takes
        # none, raising TypeError on every miss.
        default_factory = getattr(default_factory, "__wrapped__", default_factory)

        if not callable(default_factory):
            raise TypeError("default_factory must be callable")

        super().__init__(ignore_arguments(default_factory))


class KeyDefaultWeakKeyDict(weakref.WeakKeyDictionary[_KT, _VT]):
    def __init__(self, default_factory: Callable[[_KT], _VT]) -> None:
        if not callable(default_factory):
            raise TypeError("default_factory must be callable")

        super().__init__()
        self.default_factory = default_factory

    def __getitem__(self, key: _KT) -> _VT:
        try:
            return super().__getitem__(key)
        except KeyError:
            value = self.default_factory(key)
            self[key] = value
            return value

    __call__ = __getitem__

class DefaultWeakKeyDict(KeyDefaultWeakKeyDict[_KT, _VT]):
    """KeyDefaultWeakKeyDict whose factory is called with no arguments.

    The key is what the parent hands its factory; this is for the common case
    where the default does not depend on it. Wrapped with callable_tools'
    ignore_arguments, whose functools.wraps leaves `__wrapped__` pointing at
    the original -- that is what makes the unwrap below possible.
    """

    def __init__(self, default_factory: Callable[[], _VT]) -> None:
        # Unwrap first: this may be one of our own ignore_arguments adapters
        # coming back, from a caller rebuilding the mapping out of
        # `default_factory`. Wrapping it again would call the unwrapped
        # factory with no arguments through a second layer that also takes
        # none, raising TypeError on every miss.
        default_factory = getattr(default_factory, "__wrapped__", default_factory)

        if not callable(default_factory):
            raise TypeError("default_factory must be callable")

        super().__init__(ignore_arguments(default_factory))


_WeakRegistryKT = TypeVar("_WeakRegistryKT", bound=Hashable, default=int)

class WeakRegistry(Generic[_WeakRegistryKT], ABC):
    """Base class for anything that should register itself, weakly, under a
    per-subclass lookup table: `SubClass.instances[key]` finds a live
    instance without keeping it alive on its own -- once nothing else
    references it, it disappears from the table too.

    Pass `key` to __init__ to control where an instance lands; omitting it
    falls back to id(self). `instances` is a classproperty cached per owning
    class (see classproperty's own `cached=True` docs), so every subclass
    gets its own independent WeakValueDictionary instead of sharing one
    across the whole hierarchy.

    Subclassing ABC here is a documentation-only signal, not an enforced
    one -- there are no abstractmethods, so nothing actually blocks
    instantiating WeakRegistry directly.

    Two things worth knowing about the id() fallback before relying on it:
    - It only identifies an instance for as long as something *else* keeps a
      strong reference to it. Nothing here does -- that's the point of a
      weak registry -- so an instance constructed with no key and no other
      reference held anywhere can be collected (and its entry removed)
      essentially immediately.
    - `key=None` is indistinguishable from "no key given" -- there is no way
      to explicitly register an instance under the key `None` itself, since
      that is always read as "fall back to id(self)" instead.

    Pass `allow_duplicate_keys=False` as a class keyword argument right in
    the class statement to make registering an already-live key raise
    ValueError instead of silently overwriting it:

    >>> class Widget(WeakRegistry[str], allow_duplicate_keys=False): ...

    The default (True) matches plain dict-assignment semantics. Omitting it
    on a subclass inherits whatever the nearest ancestor set (normal MRO
    lookup, via __init_subclass__ only touching the attribute when the
    keyword is actually given) rather than silently resetting back to True.
    Checking `key in instances` only ever sees *live* entries -- a weak dict
    removes a dead one on its own -- so a key freed up by garbage collection
    is correctly available again even with duplicates disallowed.
    """

    __slots__ = "__weakref__",


    def __init_subclass__(cls, allow_duplicate_keys: Optional[bool] = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # None means "not given" here -- setting cls.allow_duplicate_keys
        # unconditionally would shadow whatever an ancestor already set on
        # every subclass, even ones that never asked to change it.
        if allow_duplicate_keys is not None:
            cls.__allow_duplicate_keys__ = allow_duplicate_keys

    __allow_duplicate_keys__: ClassVar[bool] = True

    if TYPE_CHECKING:
        __instances__: ClassVar[weakref.WeakValueDictionary[_WeakRegistryKT, Self]]
    else:
        @classproperty(cached=True)
        def __instances__(cls):
            return weakref.WeakValueDictionary()

    def __init__(self, key: Optional[_WeakRegistryKT] = None) -> None:
        key = id(self) if key is None else key
        instances = self.__class__.__instances__

        if not self.__allow_duplicate_keys__ and instances.get(key, self) is not self:
            raise ValueError(
                f"{self.__class__.__name__}: key {key!r} is already registered "
                "and this class does not allow duplicate keys"
            )

        instances[key] = self


class SyncAwaitableRunner:
    """Owns a background thread running a persistent asyncio event loop, and
    lets synchronous code submit awaitables to it via run_coroutine_threadsafe().

    Unlike calling run_awaitable_sync() with no `loop` (which creates and tears
    down a fresh loop per call via asyncio.run()), a SyncAwaitableRunner keeps a
    single loop alive across every .run() call, so state bound to that loop
    (tasks, connections, etc.) persists between calls.

    >>> with SyncAwaitableRunner() as runner:
    ...     runner.run(coro_one())
    ...     runner.run(coro_two())

    Pass `lazy=True` to defer creating the loop and its thread until the first
    .run() call, instead of at construction time. `loop_factory` is forwarded
    to asyncio.run() on 3.12+ (where that parameter exists); on older versions
    it is ignored with a warning rather than silently dropped.

    Concurrency contract
    --------------------
    `start()` and `close()` are the only methods that take `__lock`, and only
    around their own bookkeeping -- `run()` itself is lock-free. Two things
    make that safe:

    - **The loop stays alive for the whole shutdown drain.** close() does not
      call loop.stop() -- it sets an asyncio.Event (`stopping`) that the
      worker's own task is awaiting. Only once that task wakes up *and* has
      drained every other task still on the loop does it return, which is
      what lets asyncio.run() tear the loop down. A submission that lands
      while the drain is still spinning gets swept up by the next iteration
      instead of racing a loop that is already gone.
    - **The drain re-queries the loop's real task set every iteration**
      (`asyncio.all_tasks(loop)`) rather than trusting a separately
      maintained bookkeeping set, so there is nothing that can fall out of
      sync with what is actually still running.

    A submission that still loses the race against close() surfaces as a
    fast, clean RuntimeError -- never a hang.
    """

    def __init__(
        self,
        name: Optional[str] = None,
        lazy: bool = False,
        loop_factory: Optional[Callable[[], asyncio.AbstractEventLoop]] = None,
        ) -> None:

        if loop_factory is not None and not callable(loop_factory):
            raise TypeError(
                f"loop_factory must be callable, got {type(loop_factory).__name__!r}"
            )

        # asyncio.run() only gained loop_factory in 3.12, not 3.11.
        if sys.version_info < (3, 12) and loop_factory is not None:
            warnings.warn(
                "loop_factory is ignored on Python < 3.12 "
                "(asyncio.run() has no loop_factory parameter there); "
                "falling back to a plain asyncio.run()",
                stacklevel=2,
            )

        self.__name = name
        self.__loop_factory = loop_factory

        self.__lock = threading.RLock()

        self.__thread: Optional[threading.Thread] = None
        self.__loop: Optional[asyncio.AbstractEventLoop] = None

        self.__stopping: Optional[asyncio.Event] = None
        self.__closed: bool = False

        if not lazy:
            self.start()

    
    @property
    def started(self) -> bool:
        """Whether start() has ever spawned the thread. Never goes back to False."""
        return self.__thread is not None

    @property
    def running(self) -> bool:
        """Whether the background loop is up and able to accept work right now.

        Stricter than `started and thread.is_alive()`: the thread is alive
        throughout startup too (before _worker publishes `__stopping`), and
        again briefly during shutdown, after `stopping` is set but before the
        thread has actually finished draining and exited.
        """

        thread = self.__thread
        stopping = self.__stopping

        return (
            thread is not None
            and thread.is_alive()
            and stopping is not None
            and not stopping.is_set()
        )

    @property
    def closed(self) -> bool:
        """Whether close() has been called. Never goes back to False."""
        return self.__closed

    def start(self) -> None:
        """Start the background thread. Raises if already started or closed.

        run() calls this itself on first use and treats "already started" as
        a benign race it lost, so most callers never need to call it directly;
        it is public mainly so `lazy=True` construction can force startup (and
        block until the loop is ready, or the failure is known) ahead of the
        first run().
        """

        async def _worker() -> None:
            """The single task asyncio.run() drives for the thread's whole
            lifetime: publish `__loop`/`__stopping`, park until close() flips
            `stopping`, then drain every other task still on the loop before
            returning -- only then does asyncio.run() tear the loop down, so
            it stays running for the entire drain instead of being stopped
            out from under work still in flight.
            """

            self.__stopping = stopping = asyncio.Event()
            self.__loop = loop = asyncio.get_running_loop()

            started.set()

            await stopping.wait()

            current_task = asyncio.current_task(loop)

            assert current_task is not None

            # Rebuilt as a list every iteration -- a generator expression here
            # would be truthy even once it yields nothing (a generator object
            # is always truthy regardless of what it produces), turning this
            # into a busy-spin that never lets close() finish. Re-querying
            # all_tasks() fresh each pass also means a task created *while* an
            # earlier gather() is running is still caught by the next one,
            # without needing a separately maintained tracking set.
            while tasks := [t for t in asyncio.all_tasks(loop=loop) if t is not current_task]:
                await asyncio.gather(*tasks, return_exceptions=True)

        def _bootstrap() -> None:
            loop_factory = self.__loop_factory
            del self.__loop_factory
            coro = _worker()

            try:
                if sys.version_info < (3, 12):
                    asyncio.run(coro)
                else:
                    asyncio.run(coro, loop_factory=loop_factory)
            finally:
                self.__loop = None
                self.__stopping = None

                # Covers startup failures that happen before _worker ever
                # runs (e.g. a loop_factory that raises): without this,
                # started.wait() below would block forever, since nothing
                # else would ever set it.
                if not started.is_set():
                    started.set()

        with self.__lock:
            if self.started:
                raise RuntimeError(f"{self.__class__.__name__} is already started")
            if self.__closed:
                raise RuntimeError(f"{self.__class__.__name__} is closed")

            started = threading.Event()
            thread = threading.Thread(
                target=safe_call, 
                args=(_bootstrap,),
                kwargs={"log_exc": True},
                name=self.__name,
                daemon=True,
            ) 

            del self.__name

            thread.start()
            started.wait()

            self.__thread = thread

    def run(self, awaitable: Awaitable[_T]) -> _T:
        """Run `awaitable` on the background loop and block until it completes.

        Starts the loop on first use if it is not already started. Lock-free
        by design -- see the class docstring for why that is safe.
        """

        if not self.started:
            try:
                self.start()
            except RuntimeError:
                # Lost a race to start against another caller -- fine, unless
                # the reason is that the runner is closed, which is fatal.
                if self.closed:
                    raise

        loop = self.__loop

        if not self.running or loop is None:
            raise RuntimeError(f"{self.__class__.__name__} is not running")

        try:
            fut = asyncio.run_coroutine_threadsafe(
                awaitable if asyncio.iscoroutine(awaitable)
                else run_awaitable_in_coro(awaitable),
                loop
            )
        except AttributeError: #closed
            raise RuntimeError(
                f"{self.__class__.__name__}'s event loop disappeared while scheduling"
            ) from None

        if not loop.is_running():
            raise RuntimeError(
                f"{self.__class__.__name__}'s event loop is no longer running"
            )

        return fut.result()

    __call__ = run

    def close(self) -> None:
        """Stop the background loop and wait for it: signal `stopping`, let
        every other task on the loop drain, then wait for the thread to end.

        Safe to call concurrently and repeatedly: the first caller flips
        `__closed` under `__lock`; the rest return immediately. `loop`/
        `stopping` being None means the thread already finished on its own
        (or never got far enough to publish them) -- nothing left to signal.
        """

        with self.__lock:
            if self.__closed:
                return

            self.__closed = True

        loop = self.__loop
        stopping = self.__stopping

        if not self.started or loop is None or stopping is None:
            return

        # Hand the signal to the worker's own loop rather than setting the
        # asyncio.Event directly -- Event is not thread-safe.
        loop.call_soon_threadsafe(stopping.set)

        self.__thread.join()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()


UTC3LogFormatter = type(
    "UTC3LogFormatter", 
    (logging.Formatter, ), 
    {"converter": lambda _, stamp: datetime.fromtimestamp(stamp, tz=timezone(timedelta(hours=3))).timetuple()}
    )


__all__ = (
    "FrozenClassAttrs",
    "KeyDefaultDict",
    "AioThreadWorker",
    "MongoIndex",
    "UTC3LogFormatter",
    "hybridmethod",
    "KeyDefaultWeakValueDict",
    "DefaultWeakValueDict",
    "classproperty",
    "SyncAwaitableRunner", 
    "RestrictedProxy", 
    "WeakRestrictedProxy", 
    "KeyDefaultWeakKeyDict",
    "DefaultWeakKeyDict",
    "WeakRegistry",
)