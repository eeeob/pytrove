"""Walking a folder into an archive."""

from __future__ import annotations as _annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING

from ..._internal import _default_stability_check, _stat_is_link, _HAS_FILE_ATTRIBUTES
from ...enums import ArchiveFormat
from ...files_tools import remove_paths
from .common import _new_prefixes, _split_workers, _WalkEntry
from .rules import _Filter
from .writers import _write_tar, _write_zip

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from concurrent.futures import Executor

log = logging.getLogger(__name__)


@dataclass(slots=True)
class _Compressor:
    """Turns a folder into an archive: iterating it walks the tree, `write` fills the archive."""

    root: str
    """The folder, absolute; archive names are relative to it."""

    flt: _Filter
    """What to keep; hidden files and the archive itself are ordinary exclude rules in it."""

    follow_links: bool = False
    """Whether to archive what a link to a file inside `root` points at; directory and outside links are skipped."""

    def write(
        self,
        out: IO[bytes],
        fmt: ArchiveFormat,
        level: int | None = None,
        workers: int | Executor | None = None,
        stability_retries: int = 0,
        stability_check: Callable[[os.stat_result, str], bool] = _default_stability_check,
    ) -> None:
        """Walk the tree into `out` in the container `fmt` names.

        Args:
            out: The open destination.
            fmt: The format.
            level: The codec level; `None` for the format's default (0 is a real zip level).
            workers: A thread count or a pool.
            stability_retries: How hard to guard against concurrent edits.
            stability_check: Which files are worth guarding.
        """
        count, pool = _split_workers(workers, "compress_folder")

        if fmt is ArchiveFormat.ZIP:
            _write_zip(
                iter(self),
                out,
                6 if level is None else level,
                count,
                pool,
                stability_retries,
                stability_check,
            )
        else:
            _write_tar(iter(self), out, fmt, level, count, pool, stability_retries, stability_check)

    def __iter__(self) -> Iterator[_WalkEntry]:
        """Walk the tree with an explicit `os.scandir` stack.

        A file is asked `matches`, a directory `enter`, so an excluded
        directory is pruned whole. A directory is yielded only before the first
        kept file under it. A followed link must resolve to a file inside the root.

        Yields:
            `(absolute path, posix archive name, is directory)` for each kept entry.
        """
        root, flt, follow_links = self.root, self.flt, self.follow_links
        # Each directory carries its own archive-name prefix, so no entry needs `relpath`.
        stack = [(root, "")]
        emitted: set[str] = set()

        while stack:
            current, prefix = stack.pop()

            try:
                with os.scandir(current) as it:
                    entries = list(it)
            except OSError as exc:
                log.warning("compress_folder: cannot read directory %r (%s)", current, exc)
                continue

            for entry in entries:
                rel = prefix + entry.name

                # `DirEntry` caches the symlink bit, and on Windows the junction tag too.
                if entry.is_symlink() or (_HAS_FILE_ATTRIBUTES and _is_junction(entry)):
                    if not follow_links:
                        continue

                    dst = Path(os.path.realpath(entry.path))

                    if not dst.is_relative_to(root):
                        log.warning(
                            "compress_folder: not following %r, it leaves the folder being archived "
                            "(points at %r)",
                            entry.path,
                            str(dst),
                        )
                        continue

                    if dst.is_dir():
                        log.warning(
                            "compress_folder: not following %r, it points at directory %r, which the walk "
                            "already reaches on its own",
                            entry.path,
                            str(dst),
                        )
                        continue

                    if dst.is_file() and flt.matches(rel, entry):
                        yield from self._ancestors(rel, emitted)
                        yield entry.path, rel, False

                    continue

                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError as exc:
                    log.warning(
                        "compress_folder: cannot read the type of %r, leaving it out (%s)",
                        entry.path,
                        exc,
                    )
                    continue

                if is_dir:
                    if flt.enter(rel, entry):
                        stack.append((entry.path, f"{rel}/"))
                elif is_file and flt.matches(rel, entry):
                    yield from self._ancestors(rel, emitted)
                    yield entry.path, rel, False

    def _ancestors(self, rel: str, emitted: set[str]) -> Iterator[_WalkEntry]:
        """Yield the directories `rel` lives in, outermost first, each once per walk.

        Args:
            rel: A kept file's posix archive name.
            emitted: The directories already yielded on this walk.

        Yields:
            Each directory not yet yielded.
        """
        for branch in _new_prefixes(rel.rpartition("/")[0], emitted):
            yield os.path.join(self.root, *branch.split("/")), branch, True


def _is_junction(entry: os.DirEntry[str]) -> bool:
    """Tell whether a walked entry is a link `DirEntry.is_symlink` misses: a Windows junction.

    Read from the unfollowed `stat` `os.scandir` already cached on Windows,
    so the walk spends no `lstat` per entry on it.

    Args:
        entry: The directory entry.

    Returns:
        Whether it is a junction (or a symlink).
    """
    return _stat_is_link(entry.stat(follow_symlinks=False))


def _remove_all_but(root: Path, keep: Path) -> None:
    """Remove everything in `root` except `keep` and the directories leading to it.

    For `delete_source` when the archive was written inside the folder it
    archives. A link is removed as itself, never followed.

    Args:
        root: The folder to empty.
        keep: A path inside `root` to leave in place.

    Raises:
        OSError: The first removal that failed.
    """
    here = root

    for part in keep.relative_to(root).parts:
        kept = os.path.normcase(part)

        with os.scandir(here) as it:
            doomed = [entry.path for entry in it if os.path.normcase(entry.name) != kept]

        remove_paths(doomed)
        here = here / part


__all__ = (
    "_Compressor",
    "_is_junction",
    "_remove_all_but",
)
