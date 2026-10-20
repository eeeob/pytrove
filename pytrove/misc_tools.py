"""Deprecated: class utilities moved to `pytrove.object_tools` and `generate_secret` to `pytrove.crypto_tools`.

Every name still resolves, with a `DeprecationWarning` naming its new home.
"""

from __future__ import annotations as _annotations

from typing import Any, Final

from ._internal._deprecation import _moved_attribute

_MOVED: Final[dict[str, str]] = {
    "unwrap_cls": "pytrove.object_tools",
    "unwrap": "pytrove.object_tools",
    "patch_into": "pytrove.object_tools",
    "patch_cls": "pytrove.object_tools",
    "walk_subclasses": "pytrove.object_tools",
    "generate_secret": "pytrove.crypto_tools",
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
