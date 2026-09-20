from typing import Union, List, Callable, Optional, Awaitable, overload, Type, Tuple
from concurrent.futures import ThreadPoolExecutor

from .typings import (
    NestedContainer, Container, MaybeAwaitable, 
    MaybeAwaitableCallable, 
    _True, _False, 
    _P, _T, _ExcT, 
)
from .validate_tools import is_exception, iscoroutinefunction_wrapped, is_container
from .iter_tools import iter_flat_cont

from ._async_tools import (
    _gather_cancel_on_error, 
    _ExcFilter, 
    _ExcLogger, 
    _HARD_PROPAGATE, 
)

import asyncio
import functools
import logging
import contextvars
import inspect
import traceback


log = logging.getLogger(__file__)



def _log_exc(
    header: Optional[str],
    caller_stack: List[traceback.FrameSummary],
    exc: BaseException,
    index: Optional[int] = None,
) -> None:
    exc_trace = traceback.format_exception(type(exc), exc, exc.__traceback__)
    caller_trace = traceback.format_list(caller_stack)

    if header is None:
        header = ""

    if index is not None:
        header = f"{header} [awaitable index={index}]" if header else f"[awaitable index={index}]"

    log.error(
        "%s\n%s", 
        header, 
        "".join(caller_trace) + "".join(exc_trace)
    )


@overload
async def to_thread(
    func: Callable[_P, _T],
    *args: _P.args,
    executor: Optional[ThreadPoolExecutor] = None,
    log_exc: bool = True,
    **kwargs: _P.kwargs,
) -> _T: ...
@overload
async def to_thread(
    func: Callable[_P, _T],
    *args: _P.args,
    executor: Optional[ThreadPoolExecutor] = None,
    log_exc: bool = True,
    return_exc: _True,
    **kwargs: _P.kwargs,
) -> Union[_T, Exception]: ...

async def to_thread(
    func,
    *args,
    executor = None,
    log_exc = True, 
    return_exc = False, 
    **kwargs,
    ):
    caller_stack = traceback.extract_stack()[:-1]

    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    func = functools.partial(ctx.run, func, *args, **kwargs)
    
    
    try:
        return await loop.run_in_executor(executor, func)
    except Exception as e:
        if log_exc:
            _log_exc("error in to_thread", caller_stack, e)
        
        if return_exc:
            return e
        
        raise


@overload
async def gather_helper(
    *awaitables: NestedContainer[Optional[Awaitable[_T]]],
    log_exc: bool = True,
) -> List[_T]: ...
@overload
async def gather_helper(
    *awaitables: NestedContainer[Optional[Awaitable[_T]]],
    return_exc: _True,
    log_exc: bool = True,
) -> List[Union[_T, Exception]]: ...
async def gather_helper(
    *awaitables,
    return_exc = False,
    log_exc = True,
    ):

    caller_stack = traceback.extract_stack()[:-1]

    results = await asyncio.gather(*iter_flat_cont(awaitables), return_exceptions=return_exc)

    if log_exc and return_exc:
        for i, r in enumerate(results):
            if is_exception(r):
                _log_exc("error in gather_helper", caller_stack, r, index=i)

    return results


@overload
async def gather_abort(
    *awaitables: NestedContainer[Optional[Awaitable[_T]]], 
    log_exc: bool = True, 
) -> List[_T]: ...
@overload
async def gather_abort(
    *awaitables: NestedContainer[Optional[Awaitable[_T]]],
    return_exc: _True,
    log_exc: bool = True,
) -> List[Union[_T, Exception]]: ...
async def gather_abort(
    *awaitables, 
    return_exc = False, 
    log_exc = True, 
    ):

    caller_stack = traceback.extract_stack()[:-1]

    results = await _gather_cancel_on_error(*iter_flat_cont(awaitables), return_exceptions=return_exc)

    if log_exc and return_exc:
        for i, r in enumerate(results):
            if is_exception(r):
                _log_exc("error in gather_abort", caller_stack, r, index=i)

    return results

@overload
async def safe_await(
    awaitables: Awaitable[_T],
    *,
    log_exc: bool = True,
) -> Union[_T, Exception]: ...
@overload
async def safe_await(
    awaitables: Awaitable[_T],
    *,
    return_exc: _False,
    log_exc: bool = True,
) -> _T: ...
@overload
async def safe_await(
    awaitables: Container[NestedContainer[Optional[Awaitable[_T]]]],
    *, 
    log_exc: bool = True,
) -> List[Union[_T, Exception]]: ...
@overload
async def safe_await(
    awaitables: Container[NestedContainer[Optional[Awaitable[_T]]]],
    *, 
    return_exc: _False,
    log_exc: bool = True,
) -> List[_T]: ...
@overload
async def safe_await(
    *awaitables: NestedContainer[Optional[Awaitable[_T]]],
    log_exc: bool = True,
) -> List[Union[_T, Exception]]: ...
@overload
async def safe_await(
    *awaitables: NestedContainer[Optional[Awaitable[_T]]],
    return_exc: _False,
    log_exc: bool = True,
) -> List[_T]: ...

async def safe_await(
    *awaitables,
    return_exc = True,
    log_exc = True,
    ):

    is_not_cont_first = not is_container(awaitables[0]) if awaitables else True
    caller_stack = traceback.extract_stack()[:-1]

    results = []
    is_multi = False

    for i, awaitable in enumerate(iter_flat_cont(awaitables)):
        if not is_multi and i > 0:
            is_multi = True

        try:
            result = await awaitable
        except Exception as e:
            result = e

        if is_exception(result):
            if log_exc:
                _log_exc(
                    "error in safe_await",
                    caller_stack, result, 
                    index=i if is_multi else None,
                )
            if not return_exc:
                raise result

        results.append(result)

    return results[0] if len(results) == 1 and is_not_cont_first else results



@overload
async def asafe_call(
    awaitable: Awaitable[_T],
    *,
    include_exc: _ExcFilter = None,
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
) -> Optional[_T]: ...
@overload
async def asafe_call(
    awaitable: Awaitable[_T],
    *,
    return_exc: _False,
    include_exc: _ExcFilter = None,
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
) -> Optional[_T]: ...
@overload
async def asafe_call(
    awaitable: Awaitable[_T],
    *,
    return_exc: _True,
    include_exc: Type[_ExcT],
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
) -> Union[_T, _ExcT]: ...
@overload
async def asafe_call(
    awaitable: Awaitable[_T],
    *,
    return_exc: _True,
    include_exc: Tuple[Type[_ExcT], ...],
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
) -> Union[_T, _ExcT]: ...
@overload
async def asafe_call(
    awaitable: Awaitable[_T],
    *,
    return_exc: _True,
    include_exc: _ExcFilter = None,
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
) -> Union[_T, BaseException]: ...
@overload
async def asafe_call(
    awaitable: Awaitable[_T],
    *,
    raise_exc: _True,
    include_exc: _ExcFilter = None,
    exclude_exc: _ExcFilter = None,
    log_exc: _ExcLogger = False,
) -> _T: ...
async def asafe_call(
    awaitable,
    *,
    return_exc = False,
    raise_exc = False,
    include_exc = None,
    exclude_exc = None,
    log_exc = False,
    ):
    """await `awaitable`, swallowing whatever it raises.

    The async counterpart of callable_tools.safe_call(), for a single
    already-created awaitable rather than a callable to invoke: same
    include_exc/exclude_exc filtering, same SystemExit/KeyboardInterrupt
    hard-propagation, same bool-or-callable log_exc. Two differences:

    `log_exc`'s callable form may itself be sync or async -- if calling it
    returns an awaitable, that awaitable is awaited too before continuing.
    An exception raised either by the call itself or by awaiting its result
    is not caught; it propagates out of asafe_call, chained via `from`
    onto the original error.

    `raise_exc=True` has no sync equivalent: after `log_exc` runs (if it
    fires), the exception is always re-raised via a bare `raise` (preserving
    its original traceback) instead of being swallowed or returned --
    useful when you want the logging/handling side effect without changing
    whether the caller sees the error. Because of that, `return_exc` and
    `raise_exc` are mutually exclusive: return_exc says "hand the exception
    back as a value", raise_exc says "never hand it back at all", and
    combining them raises TypeError immediately, before `awaitable` is even
    awaited.
    """

    if return_exc and raise_exc:
        raise TypeError(
            "asafe_call: return_exc and raise_exc cannot both be True -- "
            "raise_exc means the exception is never returned, only re-raised"
        )

    if exclude_exc is not None:
        for exc_type in exclude_exc if isinstance(exclude_exc, tuple) else (exclude_exc,):
            if issubclass(exc_type, _HARD_PROPAGATE):
                raise TypeError(
                    f"exclude_exc: {exc_type.__name__} always propagates already -- "
                    "no need to list it"
                )

    try:
        return await awaitable
    except _HARD_PROPAGATE:
        raise
    except BaseException as e:
        if exclude_exc is not None and isinstance(e, exclude_exc):
            raise

        if include_exc is not None and not isinstance(e, include_exc):
            raise

        if log_exc:
            if callable(log_exc):
                try:
                    await maybe_awaitable(log_exc, e, log_exc=False)
                except BaseException as le:
                    raise le from e
            else:
                log.error("error in asafe_call(%r)" % (awaitable,), exc_info=e)

        if raise_exc:
            raise

        if return_exc:
            return e


@overload
async def maybe_awaitable(
    awaitable_or_callable: MaybeAwaitable[_P, _T],
    *args: _P.args,
    executor: Optional[ThreadPoolExecutor] = None,
    log_exc: bool = True,
    **kwargs: _P.kwargs,
) -> _T: ...
@overload
async def maybe_awaitable(
    awaitable_or_callable: MaybeAwaitable[_P, _T],
    *args: _P.args,
    executor: Optional[ThreadPoolExecutor] = None,
    return_exc: _True,
    log_exc: bool = True,
    **kwargs: _P.kwargs,
) -> Union[_T, Exception]: ...

async def maybe_awaitable(
    awaitable_or_callable,
    *args,
    executor = None, 
    return_exc = False, 
    log_exc = True,
    **kwargs,
):
    
    if inspect.isawaitable(awaitable_or_callable):
        if args or kwargs:
            raise TypeError(
                "Cannot pass args/kwargs to an already-created awaitable"
            )
        return await safe_await(
            awaitable_or_callable, 
            return_exc=return_exc, 
            log_exc=log_exc, 
        )
    elif iscoroutinefunction_wrapped(awaitable_or_callable):
        return await safe_await(
            awaitable_or_callable(*args, **kwargs),
            return_exc=return_exc,
            log_exc=log_exc,
        )
    elif callable(awaitable_or_callable):
        return await to_thread(
            awaitable_or_callable,
            *args,
            executor=executor,
            return_exc=return_exc,
            log_exc=log_exc,
            **kwargs,
        )
    else:
        raise TypeError(
            f"Expected an Awaitable or Callable, got {type(awaitable_or_callable).__name__!r}"
        )


async def safe_wait_task(task: asyncio.Task[_T], canceled_ok = True, exc_ok = False) -> Optional[_T]:
    try:
        return await task
    except asyncio.CancelledError:
        if not canceled_ok:
            raise
    except Exception:
        if not exc_ok:
            raise

async def run_awaitable_in_coro(awaitable: Awaitable[_T]) -> _T:
    return await awaitable


async def call_sync_or_await(func: MaybeAwaitableCallable[_P, _T], *args: _P.args, **kwargs: _P.kwargs) -> _T:
    result = func(*args, **kwargs)

    if inspect.isawaitable(result):
        result = await result

    return result

async def cancel_task(task: asyncio.Task, msg: Optional[str] = None) -> bool:
    """Cancel *task* and wait until its cancellation has been processed.

    Returns ``True`` when the task accepted the cancellation request and
    ``False`` when it was already done or could not be cancelled. A task
    cannot cancel itself; attempting to do so raises :class:`RuntimeError`.

    .. warning::
       The caller should avoid cancelling a parent task while that parent is
       waiting for a child task through another task. This may interrupt the
       parent before the child finishes handling cancellation and leave the
       task hierarchy in an unexpected state.
    """

    if task is asyncio.current_task():
        raise RuntimeError("Cannot cancel the current task")
    
    if not task.cancel(msg):
        return False

    await asafe_call(
        task, 
        include_exc=asyncio.CancelledError, 
        log_exc=False, 
        return_exc=False, 
        raise_exc=False, 
    )

    return True
    

    
    
__all__ = [
    "to_thread",
    "gather_helper",
    "safe_await",
    "asafe_call",
    "safe_wait_task",
    "maybe_awaitable",
    "run_awaitable_in_coro",
    "gather_abort",
    "call_sync_or_await", 
    "cancel_task", 
]