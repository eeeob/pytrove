from __future__ import annotations as _annotations

from typing import (
    Callable, Any,
    TypeAlias,
    TypeVar, Coroutine,
    Protocol, Awaitable, overload,
    Final,
)
from .typings import _P, _T, _VT, _True, _False


_Coro: TypeAlias = Coroutine[Any, Any, _T]

_ET = TypeVar("_ET", covariant=True)  # middleware(): on_error's return type -- only ever a __call__ return, never a parameter
_AT = TypeVar("_AT", covariant=True)  # middleware(): after's return type -- same reasoning


class _WaitOnErrorDecorator(Protocol[_P, _ET]):
    @overload
    def __call__(self, func: Callable[_P, _Coro[_T]]) -> Callable[_P, _Coro[_T | _ET]]: ...
    @overload
    def __call__(self, func: Callable[_P, _T]) -> Callable[_P, _T | _ET]: ...


class _AwaitOnErrorDecorator(Protocol[_P, _ET]):
    @overload
    def __call__(self, func: Callable[_P, _Coro[_T]]) -> Callable[_P, _Coro[_T | _ET]]: ...
    @overload
    def __call__(self, func: Callable[_P, _T]) -> Callable[_P, _T | Awaitable[_ET]]: ...


class _WaitAfterDecorator(Protocol[_P, _T, _AT]):
    @overload
    def __call__(self, func: Callable[_P, _Coro[_T]]) -> Callable[_P, _Coro[_AT]]: ...
    @overload
    def __call__(self, func: Callable[_P, _T]) -> Callable[_P, _AT]: ...


class _AwaitAfterDecorator(Protocol[_P, _T, _AT]):
    @overload
    def __call__(self, func: Callable[_P, _Coro[_T]]) -> Callable[_P, _Coro[_AT]]: ...
    @overload
    def __call__(self, func: Callable[_P, _T]) -> Callable[_P, _T | Awaitable[_AT]]: ...


# call_all(lazy=True)'s return type -- calling it re-enters call_all itself
# (funcs already captured are prepended), so it needs the exact same
# overload pair call_all has: no-args/lazy=False runs everything and
# returns the tuple, lazy=True captures more funcs and hands back another
# _LazyCallAll of the same _T (hence the self-reference in the second
# overload's return type).
class _LazyCallAll(Protocol[_T]):
    @overload
    def __call__(self, *funcs: Callable[[], _VT], lazy: _False = False) -> tuple[_T | _VT, ...]: ...
    @overload
    def __call__(self, *funcs: Callable[[], _VT], lazy: _True) -> _LazyCallAll[_T | _VT]: ...


_ExcFilter: TypeAlias = type[BaseException] | tuple[type[BaseException], ...] | None
_ExcLogger: TypeAlias = bool | Callable[[BaseException], Any]

# SystemExit/KeyboardInterrupt always propagate out of safe_call, unconditionally
# -- there is no override, so exclude_exc can never usefully name them.
_HARD_PROPAGATE: Final[tuple[type[SystemExit], type[KeyboardInterrupt]]] = (SystemExit, KeyboardInterrupt)
