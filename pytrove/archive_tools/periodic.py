"""Archiving folders on a schedule."""

from __future__ import annotations as _annotations

import asyncio
import logging
import time
from collections.abc import Iterator
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ..async_tools import gather_helper, safe_wait_task, to_thread
from ..data_tools.mappings import DefaultWeakValueDict
from ..enums import TimeUnit
from ..files_tools import remove_file
from ..iter_tools import iter_flat_cont
from ..typings import NestedContainer
from .compress import compress_folder

if TYPE_CHECKING:
    from ..models.archive_models import ArchiveJob

log = logging.getLogger(__name__)


class PeriodicArchiver:
    """Runs archive jobs from one scheduling task.

    It wakes every shortest `poll_interval`, and each job whose `should_run`
    agrees is dispatched as its own task, so a slow job never delays another.
    A job still running is skipped on later wakes.

    Attributes:
        jobs: The jobs.
        base_exclude: Patterns left out of every archive.
    """

    def __init__(self, jobs: NestedContainer[ArchiveJob], *, base_exclude: NestedContainer[str] = ()) -> None:
        """Hold the jobs; nothing runs until `start`.

        Args:
            jobs: The jobs, at any nesting.
            base_exclude: Patterns left out of every archive.
        """
        # `ty` binds `_T` to the container arm of the recursive `NestedContainer[_T]`, so
        # it cannot recover the leaf type (astral-sh/ty#1703); the parameter states it.
        # Quoted because `cast` evaluates its type at runtime and `ArchiveJob` is imported
        # only under `TYPE_CHECKING`: `models` sits above the tools in the import layering.
        self.jobs = tuple(cast("Iterator[ArchiveJob]", iter_flat_cont(jobs)))
        self.base_exclude = base_exclude
        self._locks: DefaultWeakValueDict[int, asyncio.Lock] = DefaultWeakValueDict(asyncio.Lock)
        self._task: asyncio.Task[None] | None = None
        self._running: set[asyncio.Task[None]] = set()
        self._active: set[int] = set()

    def _siblings(self, job: ArchiveJob) -> list[str]:
        """List the archive names of the other jobs sharing `job`'s root, to keep them out of its archive.

        Args:
            job: The job.

        Returns:
            Their archive file names.
        """
        return [other.archive_path().name for other in self.jobs if other is not job and other.root == job.root]

    def _should_run(self, job: ArchiveJob) -> bool:
        """Ask the job, or check that `min_interval` has passed since its last run.

        Args:
            job: The job.

        Returns:
            Whether it is due.
        """
        if job.should_run is not None:
            return job.should_run()

        return time.monotonic() - job.last_run >= job.min_interval

    async def create(self, job: ArchiveJob) -> Path:
        """Build a job's archive off the event loop, with every option it carries.

        Args:
            job: The job.

        Returns:
            The archive's path.
        """
        return await to_thread(partial(
            compress_folder, job.root, job.archive_path(),
            format=job.archive_format,
            include=job.include,
            # `None` stands for "no rules", which a nested rule container spells as `()`.
            exclude=[self.base_exclude, () if job.exclude is None else job.exclude, self._siblings(job)],
            exclude_hidden=job.exclude_hidden,
            stability_retries=job.stability_retries,
            level=job.level,
            workers=job.workers,
            follow_links=job.follow_links,
            fsync=job.fsync,
            stability_check=job.stability_check,
            delete_source=job.delete_source,
        ))

    async def run_job(self, job: ArchiveJob) -> None:
        """Create, hand off and delete one archive, under the job's own lock.

        A failure goes to `on_error`, or to the log. An archive that was made
        is always removed afterwards, and `last_run` is always updated.

        Args:
            job: The job.
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
                    log.error("Archive job %r failed", job.name, exc_info=e)
            finally:
                if path is not None:
                    await to_thread(partial(remove_file, path))

                object.__setattr__(job, "last_run", time.monotonic())

    async def _loop(self) -> None:
        """Wake every shortest poll interval and dispatch each due, idle job."""
        interval = min((job.poll_interval for job in self.jobs), default=TimeUnit.MINUTE * 10)

        while True:
            await asyncio.sleep(interval)

            for job in self.jobs:
                if id(job) in self._active or not self._should_run(job):
                    continue

                self._active.add(id(job))
                task = asyncio.create_task(self.run_job(job))
                self._running.add(task)
                task.add_done_callback(self._running.discard)
                task.add_done_callback(lambda _, key=id(job): self._active.discard(key))

    def start(self) -> None:
        """Start the scheduling loop; a no-op while it runs."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Cancel the loop and wait for every dispatched run to finish, cleanup included."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await safe_wait_task(self._task)

        running = list(self._running)

        for task in running:
            if not task.done():
                task.cancel()

        await gather_helper(map(safe_wait_task, running))

    async def restart(self) -> None:
        """Stop, then start again."""
        await self.stop()
        self.start()


__all__ = ("PeriodicArchiver",)
