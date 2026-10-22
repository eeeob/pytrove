"""Walking a folder into an archive."""

from __future__ import annotations as _annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING

from ..._internal._fs import _is_link
from ..._internal._stability import _default_stability_check
from ...enums import ArchiveFormat
from .common import _split_workers, _WalkEntry
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
            _write_zip(iter(self), out, 6 if level is None else level, count, pool, stability_retries, stability_check)
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
        stack = [root]
        emitted: set[str] = set()

        while stack:
            current = stack.pop()

            try:
                with os.scandir(current) as it:
                    entries = list(it)
            except OSError as exc:
                log.warning("compress_folder: cannot read directory %r (%s)", current, exc)
                continue

            for entry in entries:
                rel = os.path.relpath(entry.path, root).replace(os.sep, "/")

                if _is_link(entry.path):
                    if not follow_links:
                        continue

                    dst = Path(os.path.realpath(entry.path))

                    if not dst.is_relative_to(root):
                        log.warning("compress_folder: not following %r, it leaves the folder being archived "
                                    "(points at %r)", entry.path, str(dst))
                        continue

                    if dst.is_dir():
                        log.warning("compress_folder: not following %r, it points at directory %r, which the walk "
                                    "already reaches on its own", entry.path, str(dst))
                        continue

                    if dst.is_file() and flt.matches(rel, entry):
                        yield from self._ancestors(rel, emitted)
                        yield entry.path, rel, False

                    continue

                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError as exc:
                    log.warning("compress_folder: cannot read the type of %r, leaving it out (%s)", entry.path, exc)
                    continue

                if is_dir:
                    if flt.enter(rel, entry):
                        stack.append(entry.path)
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
        parts = rel.split("/")[:-1]

        for i in range(1, len(parts) + 1):
            branch = "/".join(parts[:i])

            if branch not in emitted:
                emitted.add(branch)
                yield os.path.join(self.root, *parts[:i]), branch, True


__all__ = ("_Compressor",)
