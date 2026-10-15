"""Helpers private to `object_tools`."""

from __future__ import annotations as _annotations

import sys
from collections.abc import Hashable

if sys.version_info >= (3, 13):
    from typing import TypeVar
else:
    from typing_extensions import TypeVar

_WeakRegistryKT = TypeVar("_WeakRegistryKT", bound=Hashable, default=int)
"""`WeakRegistry`'s key type; instances register under their `id` by default."""

__all__ = ("_WeakRegistryKT",)
