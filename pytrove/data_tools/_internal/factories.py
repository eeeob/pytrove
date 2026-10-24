"""Helpers private to `data_tools`: adapting default factories."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, Any

from ...callable_tools import ignore_arguments

if TYPE_CHECKING:
    from collections.abc import Callable

    from ...typings import _VT


def _no_arg_factory(default_factory: Callable[[], _VT]) -> Callable[[Any], _VT]:
    """Adapt a zero-argument factory to the one-argument form the keyed dicts call.

    An adapter coming back (from a caller rebuilding a dict out of its
    `default_factory`) is unwrapped first rather than wrapped twice.

    Args:
        default_factory: The zero-argument factory.

    Returns:
        A one-argument factory that ignores its argument.

    Raises:
        TypeError: If the factory is not callable.
    """
    default_factory = getattr(default_factory, "__wrapped__", default_factory)

    if not callable(default_factory):
        msg = "default_factory must be callable"
        raise TypeError(msg)

    return ignore_arguments(default_factory)


__all__ = ("_no_arg_factory",)
