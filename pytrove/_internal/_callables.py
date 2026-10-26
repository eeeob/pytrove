"""Adapting and unwrapping callables, shared by `callable_tools`, `data_tools`, `object_tools` and `validate_tools`."""

from __future__ import annotations as _annotations

import functools
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

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


def _iter_unwrap_layers(obj: Any, *, with_prop: bool) -> Iterator[Any]:
    """Yield `obj` and every layer under it, outermost first, peeling one wrapper per turn.

    Each turn takes whichever layer applies to the current object: a property's
    getter (only with `with_prop`), its `__wrapped__`, or a `functools.partial` or
    `functools.partialmethod`'s `func`. The layers may nest in any order. A class
    is never peeled, as with `inspect.unwrap` from 3.11.

    Args:
        obj: The object to peel.
        with_prop: Whether to take a property's getter.

    Yields:
        `obj`, then each peeled layer; a property without a getter ends on `None`.

    Raises:
        ValueError: If the layers loop back on themselves, or go deeper than the
            recursion limit, as `inspect.unwrap` does.
    """
    first = obj
    seen = {id(obj): obj}
    limit = sys.getrecursionlimit()
    yield obj

    while True:
        if with_prop and isinstance(obj, property):
            obj = obj.fget
        elif not isinstance(obj, type) and hasattr(obj, "__wrapped__"):
            obj = obj.__wrapped__
        elif isinstance(obj, (functools.partial, functools.partialmethod)):
            obj = obj.func
        else:
            return

        if id(obj) in seen or len(seen) >= limit:
            msg = f"wrapper loop when unwrapping {first!r}"
            raise ValueError(msg)

        # Keeping each layer alive keeps its `id` from being reused by a later one.
        seen[id(obj)] = obj
        yield obj


__all__ = ("_ignore_arguments", "_iter_unwrap_layers")
