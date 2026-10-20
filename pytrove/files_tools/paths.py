"""Turning path-likes into paths, and creating directories inline."""

from __future__ import annotations as _annotations

import os
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    from typing import Unpack
else:
    from typing_extensions import Unpack

from ..typings import PathLike
from ._internal import _MkdirOptions


def ensure_path(path: PathLike) -> Path:
    """Turn a path-like into a `Path`, returning a `Path` as it is.

    Args:
        path: A string, bytes or `os.PathLike`; bytes are decoded as `os.fsdecode` does.

    Returns:
        The path.
    """
    return path if isinstance(path, Path) else Path(os.fsdecode(path))


def resolve_path(path: PathLike, strict: bool = False) -> Path:
    """Turn a path-like into an absolute path with symlinks resolved.

    Args:
        path: A string, bytes or `os.PathLike`.
        strict: Whether a missing path raises.

    Returns:
        The resolved path.

    Raises:
        FileNotFoundError: If `strict` is set and the path does not exist.
    """
    return ensure_path(path).resolve(strict=strict)


def ensure_dir(path: PathLike, for_file: bool = False, **kwargs: Unpack[_MkdirOptions]) -> Path:
    """Create a directory and return `path` itself, for use inline.

    `write_file(ensure_dir(out / "log.txt", for_file=True), text)` creates the
    file's parent. `parents` and `exist_ok` default to `True`, unlike `mkdir`.

    Args:
        path: The directory, or a file in it when `for_file` is set.
        for_file: Whether `path` names a file whose parent is the directory to create.
        **kwargs: `Path.mkdir` arguments: `mode`, `parents`, `exist_ok`.

    Returns:
        `path` as given, as a `Path`; neither resolved nor made absolute.

    Raises:
        FileExistsError: If a file sits where the directory should be.
    """
    kwargs.setdefault("parents", True)
    kwargs.setdefault("exist_ok", True)

    path = ensure_path(path)
    (path.parent if for_file else path).mkdir(**kwargs)
    return path


__all__ = (
    "ensure_path",
    "resolve_path",
    "ensure_dir",
)
