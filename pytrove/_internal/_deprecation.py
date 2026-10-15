"""The deprecation shim behind module paths that moved."""

from __future__ import annotations as _annotations

import importlib
import warnings
from collections.abc import Mapping
from typing import Any


def _moved_attribute(module: str, moved: Mapping[str, str], name: str) -> Any:
    """Return an attribute from its new module, warning that the old path is deprecated.

    Meant to be a shim module's `__getattr__`.

    Args:
        module: The deprecated module's name.
        moved: Each old attribute name mapped to the module that now holds it.
        name: The attribute asked for.

    Returns:
        The attribute, from its new home.

    Raises:
        AttributeError: If `name` was never part of the deprecated module.
    """
    target = moved.get(name)

    if target is None:
        msg = f"module {module!r} has no attribute {name!r}"
        raise AttributeError(msg)

    warnings.warn(
        f"{module}.{name} is deprecated: import it from {target} instead. "
        f"{module} will be removed in a future release.",
        DeprecationWarning,
        stacklevel=3,
    )
    return getattr(importlib.import_module(target), name)


__all__ = ("_moved_attribute",)
