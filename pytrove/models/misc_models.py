"""Deprecated: each model moved to the module its logic belongs to.

Every name still resolves, with a `DeprecationWarning` naming its new home.
"""

from __future__ import annotations as _annotations

from typing import Any, Final

from .._internal._deprecation import _moved_attribute

_MOVED: Final[dict[str, str]] = {
    "DeferredCall": "pytrove.models",
    "DelayedCallback": "pytrove.models",
    "JsonContainer": "pytrove.models",
    "Jitter": "pytrove.models",
}
"""Each name this module used to hold, mapped to the module that holds it now."""


def __getattr__(name: str) -> Any:
    """Resolve a moved name from its new module, with a deprecation warning.

    Args:
        name: The attribute asked for.

    Returns:
        The attribute.
    """
    return _moved_attribute(__name__, _MOVED, name)


__all__ = tuple(_MOVED)
