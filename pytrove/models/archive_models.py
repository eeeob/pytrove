"""The jobs a `PeriodicArchiver` schedules."""

from __future__ import annotations as _annotations

import os
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import Executor
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from .._internal._stability import _default_stability_check
from .._internal._types import _Rule
from ..enums import ArchiveFormat, TimeUnit
from ..files_tools import resolve_path
from ..typings import NestedContainer, PathLike


@dataclass(frozen=True)
class ArchiveJob:
    """One archive a `PeriodicArchiver` builds, hands off and schedules on its own terms.

    Two jobs land in the same folder only if their own `root` says so, and
    only then does `PeriodicArchiver` exclude one job's archive from the other's.

    The fields from `include` to `delete_source` are passed as-is to
    `compress_folder()` and documented there. `delete_source=True` deletes
    `root` once the archive is written, so the next run of a periodic job
    finds nothing left to archive; it stays opt-in for that reason.
    """

    name: str
    """The job's name, used in log messages."""

    root: PathLike
    """The folder to archive, and where the archive lands; resolved to a `Path` on construction."""

    dest_name: Callable[[], str]
    """Called on every run for the archive's file name without its extension, so a dated name stays current."""

    on_archive: Callable[[ArchiveJob, Path], Awaitable[None]]
    """Awaited with the job and the archive's path once it is written."""

    on_error: Callable[[ArchiveJob, Exception], Awaitable[None]] | None = None
    """Awaited instead of `on_archive` if creating the archive or `on_archive` raised; `None` logs the failure."""

    archive_format: ArchiveFormat = ArchiveFormat.ZIP
    """The container; a string is coerced to the member on construction."""

    include: NestedContainer[_Rule] | None = None
    """Rules for what to keep, at any nesting."""

    exclude: NestedContainer[_Rule] | None = None
    """Rules for what to leave out, at any nesting."""

    exclude_hidden: bool = True
    """Whether dot-files and Windows hidden files are left out; an include path or predicate still wins."""

    stability_retries: int = 0
    """How many times to re-read a guarded file that changed while being read; 0 only warns."""

    level: int | None = None
    """The codec level; `None` takes the format's default (6 for zip and gzip, 3 for zstd)."""

    workers: int | Executor | None = None
    """A thread count (`-1` for one per core) or an `Executor` for the compression."""

    follow_links: bool = False
    """Whether to archive the file a link inside `root` points at; links out of `root` are always skipped."""

    fsync: bool = True
    """Whether the archive must survive a power loss."""

    stability_check: Callable[[os.stat_result, str], bool] = _default_stability_check
    """Which files are worth guarding, from their `stat` and path; 1 MiB and up by default."""

    delete_source: bool = False
    """Whether to remove `root` once the archive is in place; leaves a periodic job nothing to archive next."""

    should_run: Callable[[], bool] | None = None
    """Polled by the archiver; truthy runs the job. `None` runs it once `min_interval` has passed since `last_run`."""

    min_interval: float = TimeUnit.HOUR * 12
    """Seconds between runs for the default `should_run`."""

    poll_interval: float = TimeUnit.MINUTE * 10
    """Seconds between polls; the archiver wakes at the shortest one across its jobs."""

    last_run: float = field(init=False, repr=False, compare=False)
    """When the job last ran, on the `time.monotonic()` clock; the archiver updates it in place."""

    def __post_init__(self) -> None:
        """Resolve `root` and `archive_format`, and start the clock for `last_run`."""
        object.__setattr__(self, "root", resolve_path(self.root))
        object.__setattr__(self, "archive_format", ArchiveFormat(self.archive_format))
        object.__setattr__(self, "last_run", time.monotonic())

    def archive_path(self) -> Path:
        """Return where this run's archive goes; fresh on every call, since `dest_name` is.

        Returns:
            `root / "<dest_name()>.<archive_format>"`.
        """
        # `__post_init__` resolves `root` to a `Path`; the field keeps the type its callers pass.
        return cast(Path, self.root) / f"{self.dest_name()}.{self.archive_format.value}"


__all__ = ("ArchiveJob",)
