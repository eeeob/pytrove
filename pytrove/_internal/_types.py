"""Private type aliases shared by two or more sections.

They only spell signatures and are not part of the public interface; public
types, including the package's type variables, live in `pytrove.typings`.
"""

from __future__ import annotations as _annotations

import os
import tarfile
import zipfile
from collections.abc import Callable
from typing import TypeAlias

_ExcFilter: TypeAlias = type[BaseException] | tuple[type[BaseException], ...] | None
"""The exceptions `safe_call`/`asafe_call` act on: one class, a tuple of them, or `None` for all."""

_RawEntry: TypeAlias = os.DirEntry | zipfile.ZipInfo | tarfile.TarInfo | None
"""What an archive filter is shown: a folder entry when compressing, a member when extracting."""

_Rule: TypeAlias = str | os.PathLike[str] | Callable[[str, _RawEntry], bool]
"""An archive include/exclude rule: a pattern or path (text or `os.PathLike`), or a predicate over the relative path and its entry."""

__all__ = (
    "_ExcFilter",
    "_RawEntry",
    "_Rule",
)
