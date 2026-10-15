"""Extracting an archive safely."""

from __future__ import annotations as _annotations

from concurrent.futures import Executor
from pathlib import Path

from .._internal._types import _Rule
from ..enums import ArchiveFormat
from ..errors import ValidationError
from ..files_tools import remove_file, resolve_path
from ..iter_tools import iter_flat_cont
from ..typings import ArchiveLimits, NestedContainer, PathLike
from ._internal.common import _require_zstd
from ._internal.extractor import _Extractor
from ._internal.rules import _Filter


def extract_archive(
    src: PathLike,
    dest: PathLike,
    *,
    include: NestedContainer[_Rule] | None = None,
    exclude: NestedContainer[_Rule] | None = None,
    limits: ArchiveLimits = ArchiveLimits(),
    password: str | bytes | None = None,
    workers: int | Executor | None = None,
    atomic: bool = True,
    cleanup_on_error: bool = False,
    delete_archive: bool = False,
) -> Path:
    """Extract an archive into `dest` itself, refusing anything that could escape it.

    The format is read from the leading bytes, then the name. Member names are
    untrusted: an absolute or `..` name, a NUL, a backslash, an empty segment,
    or anything resolving outside `dest` (through an earlier link or an
    existing junction) is refused. Links are refused by default and never
    allowed to point outside; fifos, sockets and devices are never created.
    `include`/`exclude` follow `compress_folder`'s ladder, but a predicate's
    second argument is the member's `ZipInfo`/`TarInfo` (or `None` for an
    implied directory). Unsafe or refused members are logged and skipped. A
    container too damaged to read raises its own reader's error
    (`BadZipFile`, `ReadError`, `BadGzipFile`).

    Args:
        src: The archive.
        dest: The destination; its parent must exist.
        include: Rules for what to keep.
        exclude: Rules for what to leave out.
        limits: Ceilings against archive bombs, link/overwrite/duplicate
            policies, and `dir_check`; see `ArchiveLimits`.
        password: For legacy ZipCrypto members; WinZip AES is refused.
        workers: A thread count or an `Executor`; zip only.
        atomic: Whether to stage everything beside `dest` and move it in only
            once the whole archive has been read; an existing `dest` is merged into.
        cleanup_on_error: Without `atomic`, whether to remove what a failed run created.
        delete_archive: Whether to remove `src` after success.

    Returns:
        `dest`.

    Raises:
        ValidationError: If `src` is not a file, its format cannot be told, or
            a member contradicts its own metadata.
        ArchiveLimitError: When a ceiling is crossed.
        ArchivePolicyError: When a policy set to "error" refuses a member.
        NotADirectoryError: If `dest` exists and is not a directory.
        ImportError: For tar.zst without a zstd backend.
    """
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
        _Filter.from_rules(iter_flat_cont(include), iter_flat_cont(exclude), who="extract_archive"),
        limits,
        password.encode() if isinstance(password, str) else password,
    ).run(fmt, workers, atomic, cleanup_on_error)

    if delete_archive:
        remove_file(src)

    return dest


__all__ = ("extract_archive",)
