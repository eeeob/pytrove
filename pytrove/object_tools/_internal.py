"""Helpers private to `object_tools`."""

from __future__ import annotations as _annotations

import inspect
import sys
from collections.abc import Hashable
from typing import TYPE_CHECKING, Any

if sys.version_info >= (3, 13):
    from typing import TypeVar
else:
    from typing_extensions import TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

_WeakRegistryKT = TypeVar("_WeakRegistryKT", bound=Hashable, default=int)
"""`WeakRegistry`'s key type; instances register under their `id` by default."""


def _install(
    target: type,
    name: str,
    member: Any,
    *,
    preserve_old: bool,
    setter: Callable[[type, str, Any], None],
) -> None:
    """Set one patched member on `target`, first keeping the one it replaces as `old<name>`.

    The old member is read raw, as `inspect.getattr_static` finds it, so a
    `staticmethod`, a `classmethod` or a descriptor is kept as the object it is
    rather than as the value it resolves to on `target`.

    Args:
        target: The class being patched.
        name: The member's name.
        member: The new member, as found in the patch class's body.
        preserve_old: Whether to keep a replaced member as `old<name>`.
        setter: How to set the new member.
    """
    if preserve_old:
        try:
            old = inspect.getattr_static(target, name)
        except AttributeError:
            pass
        else:
            setattr(target, f"old{name}", old)

    setter(target, name, member)


__all__ = (
    "_install",
    "_WeakRegistryKT",
)
