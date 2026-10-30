"""Extracting an archive safely."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

from ..enums import ArchiveFormat
from ..errors import ValidationError
from ..files_tools import remove_files, resolve_path
from ..typings import ArchiveLimits, NestedContainer, PathLike
from ._internal import _Extractor, _Filter, _checked_limits, _require_zstd

if TYPE_CHECKING:
    from concurrent.futures import Executor
    from pathlib import Path

    from .._internal import _Rule


def extract_archive(
    src: PathLike,
    dest: PathLike,
    *,
    include: NestedContainer[_Rule] | None = None,
    exclude: NestedContainer[_Rule] | None = None,
    limits: ArchiveLimits | None = None,
    password: str | bytes | None = None,
    workers: int | Executor | None = None,
    atomic: bool = True,
    cleanup_on_error: bool = False,
    delete_archive: bool = False,
) -> Path:
    """Extract an archive into `dest` itself, refusing anything that could escape it.

    The format is read from the leading bytes, then the name. Member names are
    untrusted: an absolute or `..` name, a NUL, an empty segment, anything
    resolving outside `dest` (through an earlier link or an existing
    junction) and, on Windows, a `:` (an alternate data stream) or a device
    name such as `CON` or `COM1` in any segment are refused. A backslash in a
    member name is read as a separator, as the archivers that write one mean
    it. Two names for one path (`a.txt` and `./a.txt`) are duplicates. A link
    member stops the extraction with `ArchivePolicyError` by default (see
    `ArchiveLimits.symlinks`/`hardlinks`), and a link is never allowed to
    point outside, judged by the path it really resolves to; fifos, sockets
    and devices are never created. A file member never writes through
    whatever already stands at its path: that is replaced. `include`/`exclude`
    follow `compress_folder`'s ladder, but a predicate's second argument is
    the member's `ZipInfo`/`TarInfo` (or `None` for an implied directory).
    Other unsafe or refused members are logged and skipped. A container too
    damaged to read raises its own reader's error (`BadZipFile`,
    `ReadError`, `BadGzipFile`).

    Args:
        src: The archive.
        dest: The destination; its parent must exist.
        include: Rules for what to keep.
        exclude: Rules for what to leave out.
        limits: Ceilings against archive bombs, link/overwrite/duplicate
            policies, and `dir_check`; see `ArchiveLimits`. `None` uses its
            defaults. Checked before anything is read; a policy may be its
            enum member or its string value.
        password: For legacy ZipCrypto members; WinZip AES is refused.
        workers: A thread count or an `Executor`; zip only.
        atomic: Whether to stage everything beside `dest` and move it in only
            once the whole archive has been read; an existing `dest` is merged into.
        cleanup_on_error: Without `atomic`, whether to remove what a failed run created.
        delete_archive: Whether to remove `src` after success.

    Returns:
        `dest`.

    Raises:
        ValidationError: If `src` is not a file, its format cannot be told,
            `limits` is malformed, or a member contradicts its own metadata.
        FileNotFoundError: If `src` or `dest`'s parent does not exist.
        ArchiveLimitError: When a ceiling is crossed.
        ArchivePolicyError: When a policy set to "error" refuses a member.
        NotADirectoryError: If `dest` exists and is not a directory.
        ImportError: For tar.zst without a zstd backend.
    """
    checked = _checked_limits(ArchiveLimits() if limits is None else limits)
    src = resolve_path(src, strict=True)
    dest = resolve_path(dest)

    if not src.is_file():
        msg = f"extract_archive: {str(src)!r} is not a file"
        raise ValidationError(msg)

    fmt = _Extractor.detect_format(str(src))

    if fmt is ArchiveFormat.TAR_ZST:
        _require_zstd()

    _Extractor(
        src,
        dest,
        _Filter.from_rules(include, exclude, who="extract_archive"),
        checked,
        password.encode() if isinstance(password, str) else password,
    ).run(fmt, workers, atomic, cleanup_on_error)

    if delete_archive:
        remove_files(src)

    return dest


__all__ = ("extract_archive",)
