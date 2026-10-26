"""The optional archive backends, imported in one place.

Every other module reads them as attributes of this one (`backends.std_zstd`),
so there is a single name to check or replace for each backend.
"""

from __future__ import annotations as _annotations

import importlib
from typing import TYPE_CHECKING, Any

try:
    from compression import zstd as std_zstd  # type: ignore[import-not-found]  # Standard library only from 3.14.
except ImportError:
    std_zstd: ModuleType | None = None

try:
    import zstandard  # type: ignore[import-not-found]  # Optional: the `archive` extra.
except ImportError:
    zstandard: ModuleType | None = None

if TYPE_CHECKING:
    from types import ModuleType

try:
    # Imported by name: fastzip is never installed on Windows, so a static import
    # would be unresolvable there and need a suppression that goes unused elsewhere.
    WZip: Any = importlib.import_module("fastzip.write").WZip
    # Where `CompressionChooser` lives: the only way to give fastzip a deflate level.
    fastzip_chooser: Any = importlib.import_module("fastzip.chooser")
except (
    TypeError,
    ImportError,
):  # fastzip's import fails with `TypeError` on Windows, where it finds no libz.
    WZip: Any = None
    fastzip_chooser: Any = None

try:
    from pathspec import GitIgnoreSpec, PathSpec  # type: ignore[import-not-found]  # Optional: the `archive` extra.
except ImportError:
    PathSpec: Any = None
    GitIgnoreSpec: Any = None

from ..._internal import _has_requirement

# Importable is not enough: a release older than the extra allows may be installed outside it,
# and an unusable backend is dropped to `None` so the caller takes its usual fallback.
if not _has_requirement("archive", "zstandard"):
    zstandard = None

if not _has_requirement("archive", "fastzip"):
    WZip = None
    fastzip_chooser = None

if not _has_requirement("archive", "pathspec"):
    PathSpec = None
    GitIgnoreSpec = None

__all__ = (
    "GitIgnoreSpec",
    "PathSpec",
    "WZip",
    "fastzip_chooser",
    "std_zstd",
    "zstandard",
)
