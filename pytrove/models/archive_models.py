from typing import Awaitable, Callable, Optional, Union
from dataclasses import dataclass, field
from pathlib import Path
from concurrent.futures import Executor

import os
import time

from ..typings import PathLike, NestedContainer
from ..enums import ArchiveFormat, TimeUnit
from ..files_tools import resolve_path
from .._archive_tools import _Rule, _default_stability_check


@dataclass(frozen=True)
class ArchiveJob:
    """One thing a PeriodicArchiver (classes.archiver) knows how to build,
    hand off, and schedule -- entirely on its own terms, `root` and
    `archive_format` included. Two jobs land in the same folder only if
    their own `root` says so; PeriodicArchiver only ever excludes one
    job's archive from another's when that is true.

    `dest_name` is called fresh on every run -- typically closes over a
    date/time so the archive's own name is always current, rather than
    fixed once at construction.

    `should_run` is polled by the owning PeriodicArchiver; a truthy answer
    runs this job's create -> on_archive -> delete cycle. Left at None,
    the default is a plain elapsed-time check against `min_interval` --
    pass your own for a different trigger (an activity count, a size
    threshold, whatever the caller's domain is).

    `on_error` is awaited instead of `on_archive` if creating the archive or
    `on_archive` itself raised; left at None, the owning PeriodicArchiver
    logs the failure and moves on to the next run.

    Everything from `level` down is compress_folder's own -- passed through
    as-is by PeriodicArchiver.create(), and documented there, not repeated
    here. `delete_source` is compress_folder's, too, and just as real here:
    True deletes `root` itself once the archive is written, which for a
    *periodic* job means the second run finds nothing left to archive --
    almost never what a recurring job wants, so it stays opt-in rather than
    something this warns about specially.
    """

    name: str
    root: PathLike
    dest_name: Callable[[], str]
    on_archive: Callable[["ArchiveJob", Path], Awaitable[None]]
    on_error: Optional[Callable[["ArchiveJob", Exception], Awaitable[None]]] = None

    archive_format: ArchiveFormat = ArchiveFormat.ZIP
    include: Optional[NestedContainer[_Rule]] = None
    exclude: Optional[NestedContainer[_Rule]] = None
    exclude_hidden: bool = True
    stability_retries: int = 0

    level: Optional[int] = None
    workers: Optional[Union[int, Executor]] = None
    follow_links: bool = False
    fsync: bool = True
    stability_check: Callable[[os.stat_result, str], bool] = _default_stability_check
    delete_source: bool = False

    should_run: Optional[Callable[[], bool]] = None
    min_interval: float = TimeUnit.HOUR * 12
    poll_interval: float = TimeUnit.MINUTE * 10

    # Not a constructor argument -- the job's own elapsed-time bookkeeping,
    # not something a caller hands in. PeriodicArchiver reads and updates
    # this directly (via object.__setattr__, the same door __post_init__
    # uses below) instead of keeping a parallel dict of its own keyed by
    # the job -- one job, one timestamp, kept where the rest of the job's
    # state already lives.
    last_run: float = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", resolve_path(self.root))
        object.__setattr__(self, "archive_format", ArchiveFormat(self.archive_format))
        object.__setattr__(self, "last_run", time.monotonic())

    def archive_path(self) -> Path:
        """Where this run's archive will be written -- fresh every call,
        since `dest_name` is."""

        return self.root / f"{self.dest_name()}.{self.archive_format.value}"


__all__ = (
    "ArchiveJob",
)
