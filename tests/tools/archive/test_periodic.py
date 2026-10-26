from __future__ import annotations as _annotations

import asyncio
import logging
import threading
import zipfile
from typing import TYPE_CHECKING, Any, NoReturn

import pytest

import pytrove.archive_tools.periodic as archiver_module
from pytrove.archive_tools import PeriodicArchiver
from pytrove.data_tools import DefaultWeakValueDict
from pytrove.errors import ValidationError
from pytrove.models import ArchiveJob

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path


def _names(archive: Path) -> set[str]:
    with zipfile.ZipFile(archive) as zf:
        return {n for n in zf.namelist() if not n.endswith("/")}


def _noop_dest(name: str) -> Callable[[], str]:
    return lambda: name


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("a")
    (src / "b.txt").write_text("b")
    return src


def make_job(
    root: Path | str,
    name: str = "job",
    on_archive: Callable[[ArchiveJob, Path], Awaitable[None]] | None = None,
    **kw: Any,
) -> ArchiveJob:
    async def default_on_archive(job: ArchiveJob, path: Path) -> None:
        pass

    return ArchiveJob(
        name=name,
        root=root,
        dest_name=_noop_dest(name),
        on_archive=on_archive or default_on_archive,
        **kw,
    )


# --- PeriodicArchiver.create / run_job --------------------------------------


async def test_create_writes_a_real_archive(tree: Path) -> None:
    job = make_job(tree, name="out")
    archiver = PeriodicArchiver([job])

    path = await archiver.create(job)

    assert path == tree / "out.zip"
    assert _names(path) == {"a.py", "b.txt"}


async def test_create_forwards_every_remaining_compress_folder_option(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = {}

    def fake_compress_folder(src: Path, dest: Path, **kw: Any) -> Path:
        captured.update(kw)
        dest.write_text("x")
        return dest

    monkeypatch.setattr(archiver_module, "compress_folder", fake_compress_folder)

    job = make_job(
        tree,
        name="out",
        level=5,
        workers=2,
        follow_links=True,
        fsync=False,
        delete_source=True,
    )
    archiver = PeriodicArchiver([job])

    await archiver.create(job)

    assert captured["level"] == 5
    assert captured["workers"] == 2
    assert captured["follow_links"] is True
    assert captured["fsync"] is False
    assert captured["delete_source"] is True
    assert captured["stability_check"] is job.stability_check


async def test_run_job_hands_the_archive_to_on_archive_then_deletes_it(tree: Path) -> None:
    received = []

    async def on_archive(job: ArchiveJob, path: Path) -> None:
        received.append((job.name, path, path.exists()))

    job = make_job(tree, name="out", on_archive=on_archive)
    archiver = PeriodicArchiver([job])

    await archiver.run_job(job)

    assert received == [("out", tree / "out.zip", True)]
    assert not (tree / "out.zip").exists()


async def test_run_job_updates_the_jobs_own_last_run(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = make_job(tree)
    archiver = PeriodicArchiver([job])
    stamp_before = job.last_run

    monkeypatch.setattr(archiver_module.time, "monotonic", lambda: stamp_before + 1000)

    await archiver.run_job(job)

    assert job.last_run == stamp_before + 1000


async def test_run_job_calls_on_error_and_still_cleans_up(tree: Path) -> None:
    errors = []

    async def failing_on_archive(job: ArchiveJob, path: Path) -> NoReturn:
        msg = "boom"
        raise ValueError(msg)

    async def on_error(job: ArchiveJob, exc: Exception) -> None:
        errors.append((job.name, str(exc)))

    job = make_job(tree, name="out", on_archive=failing_on_archive, on_error=on_error)
    archiver = PeriodicArchiver([job])

    await archiver.run_job(job)

    assert errors == [("out", "boom")]
    assert not (tree / "out.zip").exists()


async def test_run_job_reports_a_failed_create_and_has_nothing_to_remove(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    errors = []
    removed = []

    async def on_error(job: ArchiveJob, exc: Exception) -> None:
        errors.append(str(exc))

    async def failing_create(job: ArchiveJob) -> NoReturn:
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(archiver_module, "remove_file", removed.append)

    job = make_job(tree, on_error=on_error)
    archiver = PeriodicArchiver([job])
    monkeypatch.setattr(archiver, "create", failing_create)
    stamp_before = job.last_run

    await archiver.run_job(job)

    assert errors == ["disk full"]
    assert removed == []
    assert job.last_run >= stamp_before


async def test_stop_before_start_is_a_no_op(tree: Path) -> None:
    archiver = PeriodicArchiver([make_job(tree)])

    await archiver.stop()

    assert archiver._task is None


async def test_stop_leaves_an_already_finished_run_alone(tree: Path) -> None:
    async def finished() -> None:
        return None

    archiver = PeriodicArchiver([make_job(tree)])
    task = asyncio.create_task(finished())
    await task
    archiver._running.add(task)

    await archiver.stop()

    assert not task.cancelled()


async def test_run_job_with_no_on_error_swallows_and_logs(
    tree: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def failing_on_archive(job: ArchiveJob, path: Path) -> NoReturn:
        msg = "boom"
        raise ValueError(msg)

    job = make_job(tree, name="out", on_archive=failing_on_archive)
    archiver = PeriodicArchiver([job])

    with caplog.at_level(logging.ERROR, logger="pytrove.archive_tools.periodic"):
        await archiver.run_job(job)  # must not raise

    assert "out" in caplog.text


async def test_two_jobs_in_the_same_root_exclude_each_others_archive(tree: Path) -> None:
    job_a = make_job(tree, name="a")
    job_b = make_job(tree, name="b")
    archiver = PeriodicArchiver([job_a, job_b])

    path_a = await archiver.create(job_a)
    assert "b.zip" not in _names(path_a)  # never true anyway (not a source file), but no crash
    assert archiver._siblings(job_a) == ["b.zip"]
    assert archiver._siblings(job_b) == ["a.zip"]


async def test_jobs_in_different_roots_do_not_exclude_each_other(
    tree: Path, tmp_path: Path
) -> None:
    other_root = tmp_path / "other"
    other_root.mkdir()

    job_a = make_job(tree, name="a")
    job_b = make_job(other_root, name="b")
    archiver = PeriodicArchiver([job_a, job_b])

    assert archiver._siblings(job_a) == []
    assert archiver._siblings(job_b) == []


def test_a_delete_source_job_sharing_its_root_is_refused(tree: Path) -> None:
    # Its cleanup keeps only its own archive, so the other job's would go.
    with pytest.raises(ValidationError, match="'a' has delete_source=True but shares its root"):
        PeriodicArchiver([make_job(tree, name="a", delete_source=True), make_job(tree, name="b")])


def test_a_delete_source_job_alone_in_its_root_is_accepted(tree: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()

    archiver = PeriodicArchiver(
        [
            make_job(tree, name="a", delete_source=True),
            make_job(other, name="b", delete_source=True),
        ]
    )

    assert len(archiver.jobs) == 2


# --- should_run ---------------------------------------------------------


def test_should_run_defaults_to_elapsed_time_against_min_interval(tree: Path) -> None:
    job = make_job(tree, min_interval=1000)
    archiver = PeriodicArchiver([job])

    assert archiver._should_run(job) is False


def test_should_run_true_once_min_interval_has_passed(tree: Path) -> None:
    job = make_job(tree, min_interval=0)
    archiver = PeriodicArchiver([job])

    assert archiver._should_run(job) is True


def test_should_run_uses_the_jobs_own_callable_when_given(tree: Path) -> None:
    job = make_job(tree, min_interval=999999, should_run=lambda: True)
    archiver = PeriodicArchiver([job])

    assert archiver._should_run(job) is True


def test_two_jobs_sharing_a_name_are_tracked_independently(tree: Path) -> None:
    # last_run lives on the job itself now, so two separate ArchiveJob
    # instances never share one regardless of name; only the lock (kept on
    # PeriodicArchiver, keyed by id(job)) could ever have collided on a
    # shared name, and no longer does.
    job_a = make_job(tree, name="dup", min_interval=0)
    job_b = make_job(tree, name="dup", min_interval=999999)
    archiver = PeriodicArchiver([job_a, job_b])

    assert archiver._should_run(job_a) is True
    assert archiver._should_run(job_b) is False


async def test_two_jobs_sharing_a_name_do_not_block_each_other(tree: Path, tmp_path: Path) -> None:
    # Different roots so the shared name does not also collide on the
    # archive's own filename -- only the tracking key (name vs id) is
    # under test here.
    other_root = tmp_path / "other_dup_root"
    other_root.mkdir()
    (other_root / "f.txt").write_text("f")

    order = []
    started_a = asyncio.Event()

    async def on_archive_a(job: ArchiveJob, path: Path) -> None:
        started_a.set()
        await asyncio.sleep(0.05)
        order.append("a")

    async def on_archive_b(job: ArchiveJob, path: Path) -> None:
        await started_a.wait()
        order.append("b")

    job_a = make_job(tree, name="dup", on_archive=on_archive_a)
    job_b = make_job(other_root, name="dup", on_archive=on_archive_b)
    archiver = PeriodicArchiver([job_a, job_b])

    await asyncio.gather(archiver.run_job(job_a), archiver.run_job(job_b))

    # b ran (and appended) while a was still sleeping -- had they shared one
    # lock keyed by name, b would have blocked until a's lock released.
    assert order == ["b", "a"]


# --- locks ------------------------------------------------------------


async def test_locks_are_created_lazily_and_held_only_weakly(tree: Path) -> None:
    job = make_job(tree)
    archiver = PeriodicArchiver([job])

    assert isinstance(archiver._locks, DefaultWeakValueDict)
    assert len(archiver._locks) == 0  # nothing created until first use


async def test_a_concurrent_run_of_the_same_job_waits_on_its_lock(tree: Path) -> None:
    order = []

    async def slow_on_archive(job: ArchiveJob, path: Path) -> None:
        order.append("start")
        await asyncio.sleep(0.05)
        order.append("end")

    job = make_job(tree, name="out", on_archive=slow_on_archive)
    archiver = PeriodicArchiver([job])

    await asyncio.gather(archiver.run_job(job), archiver.run_job(job))

    assert order == ["start", "end", "start", "end"]


# --- lifecycle ------------------------------------------------------------


async def test_start_creates_a_single_scheduling_task(tree: Path) -> None:
    job_a = make_job(tree, name="a", poll_interval=1000)
    job_b = make_job(tree, name="b", poll_interval=1000)
    archiver = PeriodicArchiver([job_a, job_b])

    archiver.start()
    task = archiver._task
    assert isinstance(task, asyncio.Task)
    assert not task.done()

    await archiver.stop()
    assert task.done()


async def test_start_is_a_no_op_while_the_loop_is_still_running(tree: Path) -> None:
    job = make_job(tree, poll_interval=1000)
    archiver = PeriodicArchiver([job])

    archiver.start()
    first = archiver._task
    archiver.start()

    assert archiver._task is first
    await archiver.stop()


async def test_restart_replaces_the_scheduling_task(tree: Path) -> None:
    job = make_job(tree, poll_interval=1000)
    archiver = PeriodicArchiver([job])

    archiver.start()
    first = archiver._task
    await archiver.restart()

    assert archiver._task is not first
    await archiver.stop()


async def test_loop_keeps_ticking_while_a_slow_run_is_in_flight_without_duplicating_it(
    tree: Path,
) -> None:
    finished = asyncio.Event()

    async def slow_on_archive(job: ArchiveJob, path: Path) -> None:
        await finished.wait()

    job = make_job(tree, on_archive=slow_on_archive, min_interval=0, poll_interval=0.01)
    archiver = PeriodicArchiver([job])

    archiver.start()
    await asyncio.sleep(0.05)  # several poll intervals

    # The loop never waits on the slow run, but a job that is still running
    # is not dispatched again -- one run in flight, not one queued per tick.
    assert len(archiver._running) == 1
    assert not archiver._task.done()

    finished.set()
    await archiver.stop()


async def test_run_job_a_failed_removal_neither_raises_nor_skips_last_run(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionError(13, "held")

    job = make_job(tree)
    archiver = PeriodicArchiver([job])
    stamp_before = job.last_run
    monkeypatch.setattr(archiver_module, "remove_file", refuse)
    monkeypatch.setattr(archiver_module.time, "monotonic", lambda: stamp_before + 1000)

    await archiver.run_job(job)

    assert job.last_run == stamp_before + 1000


# --- what create hands compress_folder --------------------------------------


async def test_base_exclude_takes_patterns_and_predicates(tree: Path) -> None:
    (tree / "c.log").write_text("c")
    job = make_job(tree, name="out")
    archiver = PeriodicArchiver(
        [job], base_exclude=["b.txt", lambda rel, raw: rel.endswith(".log")]
    )

    assert _names(await archiver.create(job)) == {"a.py"}


async def test_a_jobs_own_exclude_adds_to_base_exclude(tree: Path) -> None:
    job = make_job(tree, name="out", exclude="a.py")
    archiver = PeriodicArchiver([job], base_exclude="b.txt")

    assert _names(await archiver.create(job)) == set()


async def test_a_job_without_exclude_keeps_everything_base_exclude_allows(tree: Path) -> None:
    job = make_job(tree, name="out")
    archiver = PeriodicArchiver([job], base_exclude="b.txt")

    assert job.exclude is None
    assert _names(await archiver.create(job)) == {"a.py"}


async def test_siblings_with_glob_characters_are_excluded_by_exact_path(tree: Path) -> None:
    # Sibling names used to be bare string rules: a glob for `a[1].zip`, which
    # missed the file itself, and a name at any depth for the rest.
    (tree / "a[1].zip").write_text("sibling archive")
    (tree / "sub").mkdir()
    (tree / "sub" / "a[1].zip").write_text("not an archive")

    job_a = make_job(tree, name="a[1]")
    job_b = make_job(tree, name="b")
    archiver = PeriodicArchiver([job_a, job_b])

    assert _names(await archiver.create(job_b)) == {"a.py", "b.txt", "sub/a[1].zip"}


async def test_delete_source_hands_on_a_real_archive_then_leaves_root_empty(tree: Path) -> None:
    received = []

    async def on_archive(job: ArchiveJob, path: Path) -> None:
        received.append((path.exists(), _names(path)))

    job = make_job(tree, name="out", on_archive=on_archive, delete_source=True)

    await PeriodicArchiver([job]).run_job(job)

    assert received == [(True, {"a.py", "b.txt"})]
    assert list(tree.iterdir()) == []


# --- failures inside the callbacks -------------------------------------------


async def test_an_on_error_that_raises_is_logged_not_lost(
    tree: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def failing_on_archive(job: ArchiveJob, path: Path) -> NoReturn:
        msg = "boom"
        raise ValueError(msg)

    async def failing_on_error(job: ArchiveJob, exc: Exception) -> NoReturn:
        msg = "handler broke"
        raise RuntimeError(msg)

    job = make_job(tree, name="out", on_archive=failing_on_archive, on_error=failing_on_error)

    with caplog.at_level(logging.ERROR, logger="pytrove.archive_tools.periodic"):
        await PeriodicArchiver([job]).run_job(job)  # must not raise

    assert "on_error raised" in caplog.text
    assert "handler broke" in caplog.text
    assert not (tree / "out.zip").exists()


# --- stop() while the archive is still being built ----------------------------


async def test_stop_during_create_waits_for_the_thread_and_removes_its_archive(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = threading.Event(), threading.Event()
    handed: list[Path] = []

    def slow_compress_folder(src: Path, dest: Path, **kw: Any) -> Path:
        started.set()
        release.wait(5)
        dest.write_text("archive")
        return dest

    async def on_archive(job: ArchiveJob, path: Path) -> None:
        handed.append(path)

    monkeypatch.setattr(archiver_module, "compress_folder", slow_compress_folder)
    job = make_job(tree, name="out", on_archive=on_archive)
    archiver = PeriodicArchiver([job])
    run = asyncio.create_task(archiver.run_job(job))
    archiver._running.add(run)

    while not started.is_set():
        await asyncio.sleep(0.01)

    stopping = asyncio.create_task(archiver.stop())
    await asyncio.sleep(0.05)
    assert not stopping.done()  # still waiting on the thread

    release.set()
    await stopping

    assert run.cancelled()
    assert handed == []
    assert not (tree / "out.zip").exists()


# --- the scheduling loop ---------------------------------------------------------


class _Stop(Exception):
    """Ends a `_loop` run from inside the patched `asyncio.sleep`."""


def _ticking_sleep(monkeypatch: pytest.MonkeyPatch, ticks: int, intervals: list[float]) -> None:
    """Make the loop's `asyncio.sleep` record its interval and stop it after `ticks` wakes."""
    real_sleep = asyncio.sleep

    async def sleep(interval: float) -> None:
        intervals.append(interval)
        await real_sleep(0.01)  # Lets the runs dispatched on the previous tick finish.

        if len(intervals) > ticks:
            raise _Stop

    monkeypatch.setattr(archiver_module.asyncio, "sleep", sleep)


@pytest.mark.parametrize(("polls", "expected"), [((1000, 5), 5), ((), 600)])
async def test_the_loop_sleeps_the_shortest_poll_interval_or_ten_minutes(
    tree: Path, monkeypatch: pytest.MonkeyPatch, polls: tuple[float, ...], expected: float
) -> None:
    jobs = [
        make_job(tree, name=f"j{i}", poll_interval=p, min_interval=1e9) for i, p in enumerate(polls)
    ]
    intervals: list[float] = []
    _ticking_sleep(monkeypatch, 1, intervals)

    with pytest.raises(_Stop):
        await PeriodicArchiver(jobs)._loop()

    assert intervals == [expected, expected]


async def test_the_loop_dispatches_a_job_again_once_its_run_is_done(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = make_job(tree, min_interval=0)
    archiver = PeriodicArchiver([job])
    runs: list[str] = []

    async def run_job(job: ArchiveJob) -> None:
        runs.append(job.name)

    monkeypatch.setattr(archiver, "run_job", run_job)
    _ticking_sleep(monkeypatch, 3, [])

    with pytest.raises(_Stop):
        await archiver._loop()

    assert runs == ["job", "job", "job"]
    assert archiver._active == set()


async def test_a_should_run_that_raises_skips_only_its_own_job(
    tree: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken() -> bool:
        msg = "clock unreadable"
        raise RuntimeError(msg)

    bad = make_job(tree, name="bad", should_run=broken)
    good = make_job(tree, name="good", min_interval=0)
    archiver = PeriodicArchiver([bad, good])
    runs: list[str] = []

    async def run_job(job: ArchiveJob) -> None:
        runs.append(job.name)

    monkeypatch.setattr(archiver, "run_job", run_job)
    _ticking_sleep(monkeypatch, 2, [])

    with caplog.at_level(logging.ERROR, logger="pytrove.archive_tools.periodic"):
        with pytest.raises(_Stop):
            await archiver._loop()

    assert runs == ["good", "good"]
    assert "'bad': should_run raised" in caplog.text
    assert "clock unreadable" in caplog.text
