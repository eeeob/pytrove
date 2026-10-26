"""Exception handling shared by the sync and async call wrappers."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from ._types import _ExcFilter

_HARD_PROPAGATE: Final[tuple[type[SystemExit], type[KeyboardInterrupt]]] = (
    SystemExit,
    KeyboardInterrupt,
)
"""Exceptions that `safe_call`, `asafe_call` and `middleware` always let propagate.

There is no way to opt back in, so neither `include_exc` nor `exclude_exc` may
name them.
"""


def _as_tuple(exc_filter: _ExcFilter) -> tuple[type[BaseException], ...]:
    """Normalise an `include_exc`/`exclude_exc` value to a tuple.

    Args:
        exc_filter: An exception class, a tuple of them, or `None`.

    Returns:
        The classes; empty for `None`.
    """
    if exc_filter is None:
        return ()
    return exc_filter if isinstance(exc_filter, tuple) else (exc_filter,)


def _check_swallow_options(
    who: str, return_exc: bool, raise_exc: bool, include_exc: _ExcFilter, exclude_exc: _ExcFilter
) -> None:
    """Refuse the option combinations `safe_call` and `asafe_call` reject.

    Args:
        who: The public name, for the message.
        return_exc: The `return_exc` option.
        raise_exc: The `raise_exc` option.
        include_exc: The `include_exc` option.
        exclude_exc: The `exclude_exc` option.

    Raises:
        TypeError: If both flags are set, or `include_exc` or `exclude_exc` names an
            exception in `_HARD_PROPAGATE`.
    """
    if return_exc and raise_exc:
        msg = f"{who}: return_exc and raise_exc cannot both be True -- raise_exc means the exception is never returned, only re-raised"
        raise TypeError(msg)

    for name, value in (("include_exc", include_exc), ("exclude_exc", exclude_exc)):
        for exc_type in _as_tuple(value):
            if issubclass(exc_type, _HARD_PROPAGATE):
                msg = f"{who}: {name} cannot name {exc_type.__name__} -- it always propagates"
                raise TypeError(msg)


def _is_swallowed(exc: BaseException, include_exc: _ExcFilter, exclude_exc: _ExcFilter) -> bool:
    """Tell whether `safe_call` or `asafe_call` swallows `exc`; `exclude_exc` wins over `include_exc`.

    Args:
        exc: The exception raised, never one in `_HARD_PROPAGATE`.
        include_exc: The exceptions to swallow; `None` for all.
        exclude_exc: The exceptions that always propagate.

    Returns:
        Whether `exc` is swallowed rather than propagated.
    """
    if exclude_exc is not None and isinstance(exc, exclude_exc):
        return False
    return include_exc is None or isinstance(exc, include_exc)


__all__ = ("_HARD_PROPAGATE", "_check_swallow_options", "_is_swallowed")
