"""The jobs a `PeriodicArchiver` schedules."""

from __future__ import annotations as _annotations

import os
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import Executor
from dataclasses import dataclass, field
from pathlib import Path

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

    Attributes:
        name: The job's name.
        root: The folder to archive; resolved on construction.
        dest_name: Called on every run for the archive's file name, without
            its extension, so a name built from the date stays current.
        on_archive: Awaited with the job and the archive's path once it is written.
        on_error: Awaited instead of `on_archive` if creating the archive or
            `on_archive` raised; left `None`, the failure is logged.
        archive_format: The archive format.
        include: See `compress_folder()`.
        exclude: See `compress_folder()`.
        exclude_hidden: See `compress_folder()`.
        stability_retries: See `compress_folder()`.
        level: See `compress_folder()`.
        workers: See `compress_folder()`.
        follow_links: See `compress_folder()`.
        fsync: See `compress_folder()`.
        stability_check: See `compress_folder()`.
        delete_source: See `compress_folder()`.
        should_run: Polled by the archiver; a truthy answer runs the job.
            Left `None`, the job runs once `min_interval` has passed since `last_run`.
        min_interval: Seconds between runs for the default `should_run`.
        poll_interval: Seconds between polls.
        last_run: When the job last ran, on the `time.monotonic()` clock. Not
            a constructor argument: the archiver updates it in place.
    """

    name: str
    root: PathLike
    dest_name: Callable[[], str]
    on_archive: Callable[[ArchiveJob, Path], Awaitable[None]]
    on_error: Callable[[ArchiveJob, Exception], Awaitable[None]] | None = None

    archive_format: ArchiveFormat = ArchiveFormat.ZIP
    include: NestedContainer[_Rule] | None = None
    exclude: NestedContainer[_Rule] | None = None
    exclude_hidden: bool = True
    stability_retries: int = 0

    level: int | None = None
    workers: int | Executor | None = None
    follow_links: bool = False
    fsync: bool = True
    stability_check: Callable[[os.stat_result, str], bool] = _default_stability_check
    delete_source: bool = False

    should_run: Callable[[], bool] | None = None
    min_interval: float = TimeUnit.HOUR * 12
    poll_interval: float = TimeUnit.MINUTE * 10

    last_run: float = field(init=False, repr=False, compare=False)

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
        return self.root / f"{self.dest_name()}.{self.archive_format.value}"


__all__ = ("ArchiveJob",)
