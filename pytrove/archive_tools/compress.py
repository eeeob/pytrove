"""Archiving a folder."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, Final, cast

from .._internal import _Rule, _default_stability_check
from ..enums import ArchiveFormat
from ..errors import ValidationError
from ..files_tools import atomic_write, remove_folder, resolve_path
from ._internal import (
    _Compressor,
    _Filter,
    _exact_paths_rule,
    _format_from_suffix,
    _is_hidden,
    _remove_all_but,
    _require_zstd,
    _temp_file_rule,
)

if TYPE_CHECKING:
    import os
    from collections.abc import Callable
    from concurrent.futures import Executor
    from pathlib import Path

    from ..typings import NestedContainer, PathLike

_LEVELS: Final[dict[ArchiveFormat, range]] = {
    # zlib's own range, with `-1` its `Z_DEFAULT_COMPRESSION`.
    ArchiveFormat.ZIP: range(-1, 10),
    ArchiveFormat.TAR_GZ: range(-1, 10),
    # zstd's own floor (`ZSTD_minCLevel()`, the negative "fast" levels) and ceiling.
    ArchiveFormat.TAR_ZST: range(-(1 << 17), 23),
}
"""The codec levels each format accepts."""


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
    or `[` is a glob; text with `/` (`sub/x`, `./x`, `x/`) is a path anchored
    at `src`; anything else is a name matched at any depth. A `Path` is read
    as its posix text. An excluded directory is pruned whole and
    nothing inside can be included back. An include matches its own path
    only: `sub/*` is sub's direct children, `sub/**` its subtree. With any
    include rule, only matches are kept. Globs use `pathspec` with the
    `archive` extra; the `fnmatch` fallback treats `**`, a leading `/` and
    `sub/*` differently. Empty directories are left out. An archive written
    inside `src` excludes itself and its temp file, by exact path.

    Args:
        src: The folder to archive.
        dest: The archive path, or an existing directory to put `<src name>.<ext>` in.
        format: The container; read from `dest`'s extension when omitted (a
            directory means zip). An extension that disagrees raises.
        include: Rules for what to keep, at any nesting.
        exclude: Rules for what to leave out, at any nesting.
        level: The codec level: -1 to 9 for zip and gzip (6 by default), -131072
            to 22 for zstd (3 by default).
        workers: A thread count (`-1` for one per core) or an `Executor`; zip
            uses fastzip on it when available, tar.zst gives a count to the codec.
        follow_links: Whether to archive the file a link inside `src` points
            at; links to directories or out of `src` are always skipped.
        exclude_hidden: Whether to exclude dot-files and Windows hidden files.
            An include path or predicate still keeps a hidden file in a kept
            directory, but a hidden directory is pruned whole, so nothing under
            it can be included back; pass `False` and exclude what you need instead.
        fsync: Whether the archive must survive a power loss.
        stability_retries: How many times to re-read a guarded file that
            changed while being read; 0 only warns after the fact.
        stability_check: Which files are worth guarding, from their `stat` and
            path; files of 1 MiB or more by default.
        delete_source: Whether to remove `src` once the archive is in place. An
            archive written inside `src` is kept, with the directories that
            lead to it; everything else in `src` is removed.

    Returns:
        The archive's path.

    Raises:
        ValidationError: For a bad argument (an unknown `format`, a `level`
            outside its format's range), a source that is not a directory, or
            a format that cannot be told or disagrees with `dest`.
        FileNotFoundError: If `src` does not exist.
        ImportError: For tar.zst without a zstd backend.
    """
    if (
        not isinstance(stability_retries, int)
        or isinstance(stability_retries, bool)
        or stability_retries < 0
    ):
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
        try:
            fmt = ArchiveFormat(format)
        except ValueError:
            msg = (
                f"compress_folder: format takes one of {', '.join(repr(f.value) for f in ArchiveFormat)}, "
                f"not {format!r}"
            )
            raise ValidationError(msg) from None

        if named is not None and named is not fmt:
            msg = (
                f"compress_folder: format={fmt.value!r} does not match {dest.name!r}, which names a "
                f"{named.value} archive -- pass one answer or the other, not two that disagree"
            )
            raise ValidationError(msg)

    if level is not None and (
        not isinstance(level, int) or isinstance(level, bool) or level not in _LEVELS[fmt]
    ):
        allowed = _LEVELS[fmt]
        msg = f"compress_folder: level for {fmt.value} takes an int from {allowed[0]} to {allowed[-1]}, not {level!r}"
        raise ValidationError(msg)

    dest_path = dest / f"{src.name}.{fmt.value}" if into_dir else dest

    if fmt is ArchiveFormat.TAR_ZST:
        _require_zstd()

    excluded: list[NestedContainer[_Rule]] = [] if exclude is None else [exclude]
    inside = dest_path.is_relative_to(src)

    if inside:
        # A predicate on the exact path, so same-named files elsewhere in the tree are
        # kept and a name holding `[`, `*` or `?` is never read as a glob.
        here = dest_path.relative_to(src).as_posix()
        folder = here.rpartition("/")[0]
        folder = f"{folder}/" if folder else ""
        excluded += (_exact_paths_rule((here,)), _temp_file_rule(folder, f".{dest_path.name}."))

    if exclude_hidden:
        # `_is_hidden` reads only a `DirEntry`, which is all a walk shows a rule, so it
        # is narrower than `_Rule`'s second argument, which also covers extraction.
        excluded.append(cast("_Rule", _is_hidden))

    walk = _Compressor(str(src), _Filter.from_rules(include, excluded), follow_links=follow_links)

    with atomic_write(dest_path, binary=True, fsync=fsync) as out:
        walk.write(out, fmt, level, workers, stability_retries, stability_check)

    if delete_source:
        if inside:
            _remove_all_but(src, dest_path)
        else:
            remove_folder(src)

    return dest_path


backup_folder = compress_folder

__all__ = (
    "compress_folder",
    "backup_folder",
)
