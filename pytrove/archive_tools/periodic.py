"""Archiving folders on a schedule."""

from __future__ import annotations as _annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, cast

from ..async_tools import gather_helper, safe_wait_task, to_thread
from ..data_tools.mappings import DefaultWeakValueDict
from ..enums import TimeUnit
from ..errors import ValidationError
from ..files_tools import remove_file
from ..iter_tools import iter_flat_cont
from ._internal import _exact_paths_rule
from .compress import compress_folder

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from .._internal import _Rule
    from ..models.archive_models import ArchiveJob
    from ..typings import NestedContainer

log = logging.getLogger(__name__)


class PeriodicArchiver:
    """Runs archive jobs from one scheduling task.

    It wakes every shortest `poll_interval`, and each job whose `should_run`
    agrees is dispatched as its own task, so a slow job never delays another.
    A job still running is skipped on later wakes. A `should_run` that raises
    is logged and that job skipped for the tick; the others still run. A job
    with `delete_source` cannot share its `root` with another job, whose
    archive its cleanup would delete.

    Attributes:
        jobs: The jobs.
        base_exclude: Rules (patterns or predicates) left out of every archive.
    """

    def __init__(
        self, jobs: NestedContainer[ArchiveJob], *, base_exclude: NestedContainer[_Rule] = ()
    ) -> None:
        """Hold the jobs; nothing runs until `start`.

        Args:
            jobs: The jobs, at any nesting.
            base_exclude: Rules left out of every archive, as `compress_folder`'s
                `exclude` takes them.

        Raises:
            ValidationError: If a job with `delete_source` shares its `root` with another job.
        """
        # `ty` binds `_T` to the container arm of the recursive `NestedContainer[_T]`, so
        # it cannot recover the leaf type (astral-sh/ty#1703); the parameter states it.
        self.jobs = tuple(cast("Iterator[ArchiveJob]", iter_flat_cont(jobs)))
        self.base_exclude = base_exclude

        for job in self.jobs:
            if job.delete_source and any(o is not job and o.root == job.root for o in self.jobs):
                msg = (
                    f"PeriodicArchiver: job {job.name!r} has delete_source=True but shares its "
                    f"root with another job, whose archive it would delete"
                )
                raise ValidationError(msg)

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
        return [
            other.archive_path().name
            for other in self.jobs
            if other is not job and other.root == job.root
        ]

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
        siblings = self._siblings(job)

        return await to_thread(
            compress_folder,
            job.root,
            job.archive_path(),
            format=job.archive_format,
            include=job.include,
            # `None` stands for "no rules", which a nested rule container spells as `()`.
            exclude=[
                self.base_exclude,
                () if job.exclude is None else job.exclude,
                # By exact path: a name holding `[` is no glob, and a same-named file deeper down is kept.
                _exact_paths_rule(siblings) if siblings else (),
            ],
            exclude_hidden=job.exclude_hidden,
            stability_retries=job.stability_retries,
            level=job.level,
            workers=job.workers,
            follow_links=job.follow_links,
            fsync=job.fsync,
            stability_check=job.stability_check,
            delete_source=job.delete_source,
        )

    async def run_job(self, job: ArchiveJob) -> None:
        """Create, hand off and delete one archive, under the job's own lock.

        A failure goes to `on_error`, or to the log; a failure of `on_error`
        itself is logged. An archive that was made is always removed
        afterwards, and `last_run` is always updated. Cancelled while the
        archive is being built, it waits for that thread to finish (it cannot
        be interrupted), removes the archive, then lets the cancellation through.

        Args:
            job: The job.
        """
        async with self._locks[id(job)]:
            path = None

            try:
                creating = asyncio.ensure_future(self.create(job))

                try:
                    path = await asyncio.shield(creating)
                except asyncio.CancelledError:
                    # The thread outlives the cancellation; wait for its archive so `finally` removes it.
                    await asyncio.wait((creating,))

                    if not creating.cancelled() and creating.exception() is None:
                        path = creating.result()

                    raise

                await job.on_archive(job, path)
            except Exception as e:
                if job.on_error is None:
                    log.error("Archive job %r failed", job.name, exc_info=e)
                else:
                    try:
                        await job.on_error(job, e)
                    except Exception as handler_exc:
                        log.error(
                            "Archive job %r: on_error raised while handling %r",
                            job.name,
                            e,
                            exc_info=handler_exc,
                        )
            finally:
                # Returned, not raised: a failed removal must not replace the error in flight
                # nor skip the `last_run` update below; `to_thread` still logs it.
                if path is not None:
                    await to_thread(remove_file, path, return_exc=True)

                object.__setattr__(job, "last_run", time.monotonic())

    async def _loop(self) -> None:
        """Wake every shortest poll interval and dispatch each due, idle job."""
        interval = min((job.poll_interval for job in self.jobs), default=TimeUnit.MINUTE * 10)

        while True:
            await asyncio.sleep(interval)

            for job in self.jobs:
                if id(job) in self._active:
                    continue

                try:
                    due = self._should_run(job)
                except Exception:
                    log.exception(
                        "Archive job %r: should_run raised, skipping it this time", job.name
                    )
                    continue

                if not due:
                    continue

                self._active.add(id(job))
                task = asyncio.create_task(self.run_job(job))
                self._running.add(task)
                task.add_done_callback(self._running.discard)
                task.add_done_callback(lambda _, key=id(job): self._active.discard(key))  # noqa: B008 - binds this job's id now; a closure would see the loop's last job

    def start(self) -> None:
        """Start the scheduling loop; a no-op while it runs."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Cancel the loop and every dispatched run, and wait for each to finish, cleanup included.

        A run whose archive is still being built in its thread waits for that
        thread, then removes the archive, so nothing is left behind once this returns.
        """
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
