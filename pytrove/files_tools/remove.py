"""Removing files, directories and links, idempotently."""

from __future__ import annotations as _annotations

import os
from pathlib import Path
from typing import overload

from .._internal._fs import _is_dir
from ..iter_tools import dedupe, iter_flat_cont
from ..typings import NestedContainer, PathLike, _False, _True
from ._internal import _remove, _rmtree
from .paths import ensure_path


@overload
def remove_files(*files: NestedContainer[PathLike], return_exc: _False = False, log_exc: bool = False) -> list[Path]: ...
@overload
def remove_files(
    *files: NestedContainer[PathLike], return_exc: _True, log_exc: bool = False,
) -> list[Path | OSError]: ...
def remove_files(
    *files: NestedContainer[PathLike], return_exc: bool = False, log_exc: bool = False,
) -> list[Path | OSError]:
    """Unlink each path as the single entry it is: a file, a symlink or a junction.

    A link is unlinked, never followed; a real directory is refused. Paths are
    flattened from any nesting and deduplicated. A missing path counts as
    success but is left out of the result. Nothing is retried or forced.

    Args:
        *files: Paths, or containers of them, at any depth.
        return_exc: Whether to collect failures and carry on; otherwise the first one is raised.
        log_exc: Whether to log each collected failure at error level.

    Returns:
        What was removed, in order, with collected failures in place.

    Raises:
        OSError: The first failure, with `filename` set to its path, unless `return_exc` is set.
    """
    return _remove(files, os.unlink, "remove_files", return_exc, log_exc)


@overload
def remove_folders(
    *folders: NestedContainer[PathLike], return_exc: _False = False, log_exc: bool = False,
) -> list[Path]: ...
@overload
def remove_folders(
    *folders: NestedContainer[PathLike], return_exc: _True, log_exc: bool = False,
) -> list[Path | OSError]: ...
def remove_folders(
    *folders: NestedContainer[PathLike], return_exc: bool = False, log_exc: bool = False,
) -> list[Path | OSError]:
    """Remove each real directory with everything under it.

    A file, symlink or junction passed here is refused. A junction found
    inside a tree is unlinked, never followed. Same contract as `remove_files`.

    Args:
        *folders: Paths, or containers of them, at any depth.
        return_exc: Whether to collect failures and carry on; otherwise the first one is raised.
        log_exc: Whether to log each collected failure at error level.

    Returns:
        What was removed, in order, with collected failures in place.

    Raises:
        OSError: The first failure, with `filename` set to its path, unless `return_exc` is set.
    """
    return _remove(folders, _rmtree, "remove_folders", return_exc, log_exc)


@overload
def remove_paths(*paths: NestedContainer[PathLike], return_exc: _False = False, log_exc: bool = False) -> list[Path]: ...
@overload
def remove_paths(
    *paths: NestedContainer[PathLike], return_exc: _True, log_exc: bool = False,
) -> list[Path | OSError]: ...
def remove_paths(
    *paths: NestedContainer[PathLike], return_exc: bool = False, log_exc: bool = False,
) -> list[Path | OSError]:
    """Remove each path whatever it is: a real directory as a tree, anything else as one entry.

    Args:
        *paths: Paths, or containers of them, at any depth.
        return_exc: Whether to collect failures and carry on; otherwise the first one is raised.
        log_exc: Whether to log each collected failure at error level.

    Returns:
        What was removed, in order, with collected failures in place.

    Raises:
        OSError: The first failure, unless `return_exc` is set.
    """
    removed: list[Path | OSError] = []

    for path in dedupe(ensure_path(path) for path in iter_flat_cont(paths)):
        remover = remove_folders if _is_dir(path) else remove_files
        removed.extend(remover(path, return_exc=return_exc, log_exc=log_exc))

    return removed


remove_file = remove_files
remove_folder = remove_folders
remove_path = remove_paths

__all__ = (
    "remove_files",
    "remove_folders",
    "remove_paths",
    "remove_file",
    "remove_folder",
    "remove_path",
)
