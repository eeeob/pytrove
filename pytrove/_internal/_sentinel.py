"""The check behind the `object` class used as a "not passed" default."""

from __future__ import annotations as _annotations

import sys

if sys.version_info >= (3, 13):
    from typing import TypeIs
else:
    from typing import TypeGuard as TypeIs

from ..typings import _T


def _is_given(value: _T | type[object]) -> TypeIs[_T]:
    """Tell whether a parameter defaulting to the `object` class was passed.

    `value is object` is the check itself, but a type checker cannot narrow
    `_T | type[object]` by identity with a class; this narrows it to `_T`.

    Args:
        value: The parameter's value.

    Returns:
        Whether it is anything but the `object` class.
    """
    return value is not object


__all__ = ("_is_given",)
