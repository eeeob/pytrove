"""Archiving a folder."""

from __future__ import annotations as _annotations

import os
from collections.abc import Callable
from concurrent.futures import Executor
from pathlib import Path

from .._internal._stability import _default_stability_check
from .._internal._types import _Rule
from ..enums import ArchiveFormat
from ..errors import ValidationError
from ..files_tools import atomic_write, remove_folder, resolve_path
from ..iter_tools import iter_flat_cont
from ..typings import NestedContainer, PathLike
from ._internal.common import _format_from_suffix, _is_hidden, _require_zstd, _temp_file_rule
from ._internal.compressor import _Compressor
from ._internal.rules import _Filter


def compress_folder(
    src: PathLike,
    dest: PathLike,
    *,
    format: ArchiveFormat | str | None = None,
    include: NestedContainer[_Rule] | None = None,
    exclude: NestedContainer[_Rule] | None = None,
    level: int | None = None,
    workers: int | Executor | None = None,
    follow_links: bool = False,
    exclude_hidden: bool = True,
    fsync: bool = True,
    stability_retries: int = 0,
    stability_check: Callable[[os.stat_result, str], bool] = _default_stability_check,
    delete_source: bool = False,
) -> Path:
    """Archive a folder, written atomically, and return the archive's path.

    Rules decide what goes in, first match wins: include path, exclude path,
    include predicate, exclude predicate, include name, exclude name, exclude
    glob, include glob. A rule's kind is read off it: a callable
    `(relative path, os.DirEntry) -> bool` is a predicate; text with `*`, `?`
    or `[` is a glob; text with `/` is a path anchored at `src`; anything else
    is a name matched at any depth. An excluded directory is pruned whole and
    nothing inside can be included back. An include matches its own path
    only: `sub/*` is sub's direct children, `sub/**` its subtree. With any
    include rule, only matches are kept. Globs use `pathspec` with the
    `archive` extra; the `fnmatch` fallback treats `**`, a leading `/` and
    `sub/*` differently. Empty directories are left out. An archive written
    inside `src` excludes itself and its temp file.

    Args:
        src: The folder to archive.
        dest: The archive path, or an existing directory to put `<src name>.<ext>` in.
        format: The container; read from `dest`'s extension when omitted (a
            directory means zip). An extension that disagrees raises.
        include: Rules for what to keep, at any nesting.
        exclude: Rules for what to leave out, at any nesting.
        level: The codec level; 6 for zip and gzip, 3 for zstd by default.
        workers: A thread count (`-1` for one per core) or an `Executor`; zip
            uses fastzip on it when available, tar.zst gives a count to the codec.
        follow_links: Whether to archive the file a link inside `src` points
            at; links to directories or out of `src` are always skipped.
        exclude_hidden: Whether to exclude dot-files and Windows hidden files;
            an include path or predicate still wins.
        fsync: Whether the archive must survive a power loss.
        stability_retries: How many times to re-read a guarded file that
            changed while being read; 0 only warns after the fact.
        stability_check: Which files are worth guarding, from their `stat` and
            path; files of 1 MiB or more by default.
        delete_source: Whether to remove `src` once the archive is in place.

    Returns:
        The archive's path.

    Raises:
        ValidationError: For a bad argument, a source that is not a directory,
            or a format that cannot be told or disagrees with `dest`.
        ImportError: For tar.zst without a zstd backend.
    """
    if not isinstance(stability_retries, int) or isinstance(stability_retries, bool) or stability_retries < 0:
        msg = f"compress_folder: stability_retries takes a non-negative int, not {stability_retries!r}"
        raise ValidationError(msg)

    if not callable(stability_check):
        msg = f"compress_folder: stability_check takes a callable, not {stability_check!r}"
        raise ValidationError(msg)

    src = resolve_path(src, strict=True)
    dest = resolve_path(dest)

    if not src.is_dir():
        msg = f"compress_folder: {str(src)!r} is not a directory"
        raise ValidationError(msg)

    into_dir = dest.is_dir()
    named = None if into_dir else _format_from_suffix(dest.name)

    if format is None:
        if named is None and not into_dir:
            msg = (
                f"compress_folder: cannot tell what format {dest.name!r} should be -- end it with one of "
                f"{', '.join('.' + f.value for f in ArchiveFormat)}, or pass format="
            )
            raise ValidationError(msg)

        fmt = named or ArchiveFormat.ZIP
    else:
        fmt = ArchiveFormat(format)

        if named is not None and named is not fmt:
            msg = (
                f"compress_folder: format={fmt.value!r} does not match {dest.name!r}, which names a "
                f"{named.value} archive -- pass one answer or the other, not two that disagree"
            )
            raise ValidationError(msg)

    dest_path = dest / f"{src.name}.{fmt.value}" if into_dir else dest

    if fmt is ArchiveFormat.TAR_ZST:
        _require_zstd()

    if dest_path.is_relative_to(src):
        # Anchored at the archive's own place, so same-named files elsewhere in the tree are kept.
        here = dest_path.relative_to(src).as_posix()
        folder = here.rpartition("/")[0]
        folder = f"{folder}/" if folder else ""
        exclude = (f"/{here}", _temp_file_rule(folder, f".{dest_path.name}."), exclude)

    if exclude_hidden:
        exclude = (_is_hidden, exclude)

    walk = _Compressor(
        str(src),
        _Filter.from_rules(iter_flat_cont(include), iter_flat_cont(exclude)),
        follow_links=follow_links,
    )

    with atomic_write(dest_path, binary=True, fsync=fsync) as out:
        walk.write(out, fmt, level, workers, stability_retries, stability_check)

    if delete_source:
        remove_folder(src)

    return dest_path


backup_folder = compress_folder

__all__ = (
    "compress_folder",
    "backup_folder",
)
