from typing import List, Optional, Set, TYPE_CHECKING
from pathlib import Path

import asyncio
import logging
import time

from ..typings import NestedContainer
from ..enums import TimeUnit
from ..files_tools import remove_file
from ..archive_tools import compress_folder
from ..async_tools import to_thread
from ..iter_tools import iter_flat_cont
from ..async_tools import safe_wait_task, gather_helper

from .misc_classes import DefaultWeakValueDict

if TYPE_CHECKING:
    from ..models.archive_models import ArchiveJob

log = logging.getLogger(__name__)


class PeriodicArchiver:
    """Runs every one of `jobs` off a single scheduling task, sleeping for
    the shortest `poll_interval` among them and checking each job's own
    should_run() on every wake -- a job that says yes is dispatched as its
    own fire-and-forget task (run_job), never awaited in-line, so a slow
    or locked job never delays the next wake-up or a sibling's turn.

    Nothing here knows about what an archive is for, where it goes once
    built, or what should trigger a run -- see ArchiveJob for what every
    job supplies about itself. `base_exclude` is the one thing genuinely
    shared across jobs: patterns kept out of every archive regardless of
    which job or root it belongs to.
    """

    def __init__(self, jobs: NestedContainer["ArchiveJob"], *, base_exclude: NestedContainer = (),):
        self.jobs = tuple(iter_flat_cont(jobs))
        self.base_exclude = base_exclude

        self._locks: DefaultWeakValueDict[int, asyncio.Lock] = DefaultWeakValueDict(asyncio.Lock)

        self._task: Optional["asyncio.Task[None]"] = None
        self._running: Set["asyncio.Task[None]"] = set()

    def _siblings(self, job: "ArchiveJob") -> List[str]:
        """Every other job's own archive name, but only among jobs that
        share `job`'s root -- a job living somewhere else can never collide
        with this one, so it has nothing to be excluded for."""

        return [
            other.archive_path().name
            for other in self.jobs
            if other is not job and other.root == job.root
        ]

    def _should_run(self, job: "ArchiveJob") -> bool:
        if job.should_run is not None:
            return job.should_run()

        return time.monotonic() - job.last_run >= job.min_interval

    async def create(self, job: "ArchiveJob") -> Path:
        """Build `job`'s archive and return its path -- off the event loop,
        via to_thread, same as the rest of a job's own cycle (run_job).

        Every compress_folder knob `job` carries (level, workers,
        follow_links, fsync, stability_check, delete_source -- see
        ArchiveJob) is forwarded through as-is; only `exclude` is not
        job.exclude verbatim, since base_exclude and sibling exclusion are
        folded in alongside it here.
        """

        return await to_thread(
            compress_folder, job.root, job.archive_path(),
            format=job.archive_format,
            include=job.include,
            exclude=[self.base_exclude, job.exclude, self._siblings(job)],
            exclude_hidden=job.exclude_hidden,
            stability_retries=job.stability_retries,
            level=job.level,
            workers=job.workers,
            follow_links=job.follow_links,
            fsync=job.fsync,
            stability_check=job.stability_check,
            delete_source=job.delete_source,
        )

    async def run_job(self, job: "ArchiveJob") -> None:
        """create -> on_archive -> delete, once, for `job` alone --
        guarded by `job`'s own lock so a slow on_archive never overlaps a
        second run of the same job. `on_error` (or the default log) runs
        in place of `on_archive` on failure; either way, an archive that
        was actually created is always removed afterward.
        """

        async with self._locks[id(job)]:
            path = None

            try:
                path = await self.create(job)
                await job.on_archive(job, path)
            except Exception as e:
                if job.on_error is not None:
                    await job.on_error(job, e)
                else:
                    log.exception("Archive job %r failed", job.name, exc_info=e)
            finally:
                if path is not None:
                    await to_thread(remove_file, path)

                object.__setattr__(job, "last_run", time.monotonic())

    async def _loop(self) -> None:
        interval = min((job.poll_interval for job in self.jobs), default=TimeUnit.MINUTE * 10)

        while True:
            await asyncio.sleep(interval)

            for job in self.jobs:
                if self._should_run(job):
                    task = asyncio.create_task(self.run_job(job))
                    self._running.add(task)
                    task.add_done_callback(self._running.discard)

    def start(self) -> None:
        """Start the scheduling loop. A no-op while it is already running."""

        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Cancel the scheduling loop and wait for every job run it has
        dispatched so far to actually finish -- a run_job() in flight is
        allowed to reach its own finally (the archive is still deleted)
        before being awaited out."""

        if self._task is not None and not self._task.done():
            self._task.cancel()
            await safe_wait_task(self._task)

        running = list(self._running)

        for task in running:
            if not task.done():
                task.cancel()
            
        await gather_helper(map(safe_wait_task, running))

    async def restart(self) -> None:
        await self.stop()
        self.start()


__all__ = (
    "PeriodicArchiver",
)
