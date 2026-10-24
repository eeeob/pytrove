"""Adapting a callable's signature, shared by `callable_tools` and `data_tools`."""

from __future__ import annotations as _annotations

import functools
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..typings import _T


def _ignore_arguments(func: Callable[[], _T]) -> Callable[..., _T]:
    """Wrap a zero-argument function so it accepts and ignores any arguments.

    Lives here, not in `callable_tools`, so `data_tools` can use it without
    importing `callable_tools`, which imports `async_tools`.

    Args:
        func: The function.

    Returns:
        A wrapper calling `func()` whatever it is passed.
    """

    @functools.wraps(func)
    def wrapper(*_: Any, **__: Any) -> _T:
        """Call `func` with no arguments."""
        return func()

    return wrapper


__all__ = ("_ignore_arguments",)
