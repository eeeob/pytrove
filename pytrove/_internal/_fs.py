"""Filesystem predicates and buffer sizes shared by the files and archive tools."""

from __future__ import annotations as _annotations

import os
import stat
from typing import Final

from ..typings import PathLike

_COPY_BUF: Final[int] = 1 << 20
"""Bytes held in memory per copy step, so copying a large file costs this and not its size."""

_HAS_FILE_ATTRIBUTES: Final[bool] = hasattr(os.stat_result, "st_file_attributes")
"""Whether `os.lstat` reports Windows file attributes, which is how a junction is recognised."""


def _is_link(path: PathLike) -> bool:
    """Tell whether `path` is a symbolic link or a Windows junction.

    `os.path.islink` is `False` for a junction on every supported version,
    yet a junction redirects a directory exactly as a symlink does, so a
    remover or walker that followed it would act on the tree it names.
    Only the junction's reparse tag counts: other reparse points (cloud
    placeholders, deduplicated files) are ordinary files or directories.

    Args:
        path: The path to inspect. It is never followed.

    Returns:
        `True` for a symlink or a junction, and `False` otherwise,
        including when `path` does not exist or cannot be read.
    """
    if not _HAS_FILE_ATTRIBUTES:
        return os.path.islink(path)

    try:
        st = os.lstat(path)
    except OSError:
        return False

    # The three names below exist only on Windows, which `_HAS_FILE_ATTRIBUTES`
    # guards at runtime. `ty` cannot narrow on that flag (the tests patch it, so
    # it cannot become a `sys.platform` check), and reports them on Linux.
    return stat.S_ISLNK(st.st_mode) or bool(
        st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT  # ty: ignore[unresolved-attribute]
        and st.st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT  # ty: ignore[unresolved-attribute]
    )


def _is_dir(path: PathLike) -> bool:
    """Tell whether `path` is a real directory rather than a link to one.

    Args:
        path: The path to inspect. It is never followed.

    Returns:
        `True` only for a directory that is neither a symlink nor a
        junction, and `False` when `path` does not exist or cannot be read.
    """
    try:
        st = os.lstat(path)
    except OSError:
        return False

    return stat.S_ISDIR(st.st_mode) and not _is_link(path)


__all__ = (
    "_is_dir",
    "_is_link",
    "_COPY_BUF",
)
