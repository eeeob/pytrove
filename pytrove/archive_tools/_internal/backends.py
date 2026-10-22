"""The optional archive backends, imported in one place.

Every other module reads them as attributes of this one (`backends.std_zstd`),
so there is a single name to check or replace for each backend.
"""

from __future__ import annotations as _annotations

import importlib
from typing import TYPE_CHECKING, Any

try:
    from compression import zstd as std_zstd  # type: ignore[import-not-found, ty:unresolved-import]  # Standard library only from 3.14.
except ImportError:
    std_zstd: ModuleType | None = None

try:
    import zstandard
except ImportError:
    zstandard: ModuleType | None = None

if TYPE_CHECKING:
    from types import ModuleType

try:
    # Imported by name: fastzip is never installed on Windows, so a static import
    # would be unresolvable there and need a suppression that goes unused elsewhere.
    WZip: Any = importlib.import_module("fastzip.write").WZip
except (TypeError, ImportError):  # fastzip's import fails with `TypeError` on Windows, where it finds no libz.
    WZip: Any = None

try:
    from pathspec import GitIgnoreSpec, PathSpec
except ImportError:
    PathSpec: Any = None
    GitIgnoreSpec: Any = None

__all__ = (
    "GitIgnoreSpec",
    "PathSpec",
    "WZip",
    "std_zstd",
    "zstandard",
)
