"""Deprecated: the classes now live in the section their logic belongs to.

Every name still resolves, with a `DeprecationWarning` naming its new home.
"""

from __future__ import annotations as _annotations

from typing import Any, Final

from .._internal._deprecation import _moved_attribute

_MOVED: Final[dict[str, str]] = {
    "AioThreadWorker": "pytrove.async_tools",
    "SyncAwaitableRunner": "pytrove.async_tools",
    "KeyDefaultDict": "pytrove.data_tools",
    "KeyDefaultWeakValueDict": "pytrove.data_tools",
    "DefaultWeakValueDict": "pytrove.data_tools",
    "KeyDefaultWeakKeyDict": "pytrove.data_tools",
    "DefaultWeakKeyDict": "pytrove.data_tools",
    "classproperty": "pytrove.object_tools",
    "hybridmethod": "pytrove.object_tools",
    "FrozenClassAttrs": "pytrove.object_tools",
    "WeakRegistry": "pytrove.object_tools",
    "RestrictedProxy": "pytrove.object_tools",
    "WeakRestrictedProxy": "pytrove.object_tools",
    "MongoIndex": "pytrove.mongo_tools",
    "UTC3LogFormatter": "pytrove.logging_tools",
    "PeriodicArchiver": "pytrove.archive_tools",
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
