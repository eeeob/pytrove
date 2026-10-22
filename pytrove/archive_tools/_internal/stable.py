"""Reading a file that may be edited while it is archived."""

from __future__ import annotations as _annotations

import logging
import os
import shutil
import stat
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)


def _same_stat(a: os.stat_result, b: os.stat_result) -> bool:
    """Tell whether two `stat` results describe an unchanged file.

    Size, mtime and ctime: on POSIX ctime moves on any change and cannot be
    set back; on Windows it is the creation time and never moves, which is harmless.

    Args:
        a: The earlier result.
        b: The later result.

    Returns:
        Whether nothing observable changed in between.
    """
    return (a.st_size, a.st_mtime_ns, a.st_ctime_ns) == (b.st_size, b.st_mtime_ns, b.st_ctime_ns)


def _warn_if_changed(path: str, before: os.stat_result | None) -> None:
    """Warn when a file archived without a guard changed during the write.

    One `stat` after the write, against the one taken before it; nothing is
    retried. A missing `before`, or a file gone afterwards, says nothing.

    Args:
        path: The file just written into the archive.
        before: Its `stat` from before the write.
    """
    if before is None:
        return

    try:
        after = os.stat(path)
    except OSError:
        return

    if not _same_stat(before, after):
        log.warning(
            "compress_folder: %r changed while being archived -- the archived copy may mix bytes from before "
            "and after the change. Pass stability_retries>0 to guard against this.",
            path,
        )


def _read_stable(path: str, retries: int) -> tuple[str, os.stat_result, bool]:
    """Copy a file to a temp file, retrying until a copy is bracketed by two equal `stat`s.

    The temp file gets the verified mtime and mode, so the archive builds the
    member exactly as it would from `path`. The caller removes it.

    Args:
        path: The file to copy.
        retries: How many extra attempts to make.

    Returns:
        The temp path, the verified `stat`, and whether any attempt was stable;
        the last copy is returned even when none was.

    Raises:
        OSError: If the file cannot be read; the temp file is removed first.
        ValueError: If `retries` is negative.
    """
    tmp_path: str | None = None
    last_stat: os.stat_result | None = None
    settled = False

    try:
        for attempt in range(retries + 1):
            if tmp_path is not None:
                os.unlink(tmp_path)

            fd, tmp_path = tempfile.mkstemp(prefix="pytrove-stability-")
            os.close(fd)  # `shutil.copyfile` opens its own handle to it.

            before = os.stat(path)
            shutil.copyfile(path, tmp_path)
            after = os.stat(path)
            last_stat = before

            if _same_stat(before, after):
                settled = True
                break

            log.info(
                "compress_folder: %r changed while being read (attempt %d/%d), reading it again",
                path,
                attempt + 1,
                retries + 1,
            )

        if tmp_path is None or last_stat is None:
            # Only a negative `retries` skips the loop; `_stable_source` never passes one.
            msg = f"_read_stable: retries must be at least 0, not {retries!r}"
            raise ValueError(msg)

        os.utime(tmp_path, ns=(last_stat.st_atime_ns, last_stat.st_mtime_ns))
        os.chmod(tmp_path, stat.S_IMODE(last_stat.st_mode))
    except Exception:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise

    return tmp_path, last_stat, settled


def _stable_source(
    path: str,
    retries: int,
    check: Callable[[os.stat_result, str], bool],
) -> tuple[bool, str | None, os.stat_result | None]:
    """Decide what a writer archives for one file: the file itself, or a stable copy.

    A file is guarded only when `retries` is above 0 and `check` approves its
    `stat`. The `stat` taken here doubles as the "before" of `_warn_if_changed`.

    Args:
        path: The file about to be archived.
        retries: `stability_retries`.
        check: `stability_check`.

    Returns:
        Whether to skip the file, the temp copy to archive instead (or `None`),
        and the `stat` taken before.
    """
    try:
        before_stat = os.stat(path)
    except OSError:
        before_stat = None

    if retries <= 0 or before_stat is None or not check(before_stat, path):
        return False, None, before_stat

    try:
        tmp_path, _, settled = _read_stable(path, retries)
    except OSError as exc:
        log.warning("compress_folder: skipped %r (%s)", path, exc)
        return True, None, before_stat

    if settled:
        log.debug("compress_folder: %r read and verified stable before archiving", path)
    else:
        log.warning(
            "compress_folder: %r kept changing across %d read attempt(s), archiving the last one anyway -- its "
            "content may not match any single instant",
            path,
            retries + 1,
        )

    return False, tmp_path, before_stat


__all__ = (
    "_read_stable",
    "_same_stat",
    "_stable_source",
    "_warn_if_changed",
)
