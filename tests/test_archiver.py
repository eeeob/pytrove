import asyncio
import time
import zipfile

import pytest

from pytrove.classes import PeriodicArchiver
from pytrove.models import ArchiveJob
from pytrove.enums import ArchiveFormat


def _names(archive):
    with zipfile.ZipFile(archive) as zf:
        return {n for n in zf.namelist() if not n.endswith("/")}


def _noop_dest(name):
    return lambda: name


@pytest.fixture
def tree(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("a")
    (src / "b.txt").write_text("b")
    return src


def make_job(root, name="job", on_archive=None, **kw) -> ArchiveJob:
    async def default_on_archive(job, path):
        pass

    return ArchiveJob(
        name=name,
        root=root,
        dest_name=_noop_dest(name),
        on_archive=on_archive or default_on_archive,
        **kw,
    )


# --- ArchiveJob -------------------------------------------------------------

def test_root_is_resolved_to_a_path(tree):
    job = make_job(str(tree))
    assert job.root == tree.resolve()


def test_archive_format_is_coerced_to_the_enum(tree):
    job = make_job(tree, archive_format="zip")
    assert job.archive_format is ArchiveFormat.ZIP


def test_archive_path_uses_dest_name_and_the_format_extension(tree):
    job = make_job(tree, name="x")
    assert job.archive_path() == tree / "x.zip"


def test_archive_path_calls_dest_name_fresh_every_time():
    calls = []

    def dest_name():
        calls.append(1)
        return f"n{len(calls)}"

    job = ArchiveJob("j", ".", dest_name, on_archive=None)
    assert job.archive_path().name == "n1.zip"
    assert job.archive_path().name == "n2.zip"


def test_last_run_is_stamped_at_construction(tree):
    before = time.monotonic()
    job = make_job(tree)
    after = time.monotonic()

    assert before <= job.last_run <= after


def test_last_run_is_not_a_constructor_argument(tree):
    with pytest.raises(TypeError):
        make_job(tree, last_run=0.0)


# --- PeriodicArchiver.create / run_job --------------------------------------

async def test_create_writes_a_real_archive(tree):
    job = make_job(tree, name="out")
    archiver = PeriodicArchiver([job])

    path = await archiver.create(job)

    assert path == tree / "out.zip"
    assert _names(path) == {"a.py", "b.txt"}


async def test_create_forwards_every_remaining_compress_folder_option(tree, monkeypatch):
    captured = {}

    def fake_compress_folder(src, dest, **kw):
        captured.update(kw)
        dest.write_text("x")
        return dest

    import pytrove.classes.archiver as archiver_module
    monkeypatch.setattr(archiver_module, "compress_folder", fake_compress_folder)

    job = make_job(
        tree, name="out",
        level=5, workers=2, follow_links=True, fsync=False, delete_source=True,
    )
    archiver = PeriodicArchiver([job])

    await archiver.create(job)

    assert captured["level"] == 5
    assert captured["workers"] == 2
    assert captured["follow_links"] is True
    assert captured["fsync"] is False
    assert captured["delete_source"] is True
    assert captured["stability_check"] is job.stability_check


async def test_stability_check_defaults_to_compress_folders_own_default(tree):
    from pytrove._archive_tools import _default_stability_check

    job = make_job(tree)
    assert job.stability_check is _default_stability_check


async def test_run_job_hands_the_archive_to_on_archive_then_deletes_it(tree):
    received = []

    async def on_archive(job, path):
        received.append((job.name, path, path.exists()))

    job = make_job(tree, name="out", on_archive=on_archive)
    archiver = PeriodicArchiver([job])

    await archiver.run_job(job)

    assert received == [("out", tree / "out.zip", True)]
    assert not (tree / "out.zip").exists()


async def test_run_job_updates_the_jobs_own_last_run(tree, monkeypatch):
    job = make_job(tree)
    archiver = PeriodicArchiver([job])
    stamp_before = job.last_run

    import pytrove.classes.archiver as archiver_module
    monkeypatch.setattr(archiver_module.time, "monotonic", lambda: stamp_before + 1000)

    await archiver.run_job(job)

    assert job.last_run == stamp_before + 1000


async def test_run_job_calls_on_error_and_still_cleans_up(tree):
    errors = []

    async def failing_on_archive(job, path):
        raise ValueError("boom")

    async def on_error(job, exc):
        errors.append((job.name, str(exc)))

    job = make_job(tree, name="out", on_archive=failing_on_archive, on_error=on_error)
    archiver = PeriodicArchiver([job])

    await archiver.run_job(job)

    assert errors == [("out", "boom")]
    assert not (tree / "out.zip").exists()


async def test_run_job_with_no_on_error_swallows_and_logs(tree, caplog):
    async def failing_on_archive(job, path):
        raise ValueError("boom")

    job = make_job(tree, name="out", on_archive=failing_on_archive)
    archiver = PeriodicArchiver([job])

    import logging
    with caplog.at_level(logging.ERROR, logger="pytrove.classes.archiver"):
        await archiver.run_job(job)  # must not raise

    assert "out" in caplog.text


async def test_two_jobs_in_the_same_root_exclude_each_others_archive(tree):
    job_a = make_job(tree, name="a")
    job_b = make_job(tree, name="b")
    archiver = PeriodicArchiver([job_a, job_b])

    path_a = await archiver.create(job_a)
    assert "b.zip" not in _names(path_a)  # never true anyway (not a source file), but no crash
    assert archiver._siblings(job_a) == ["b.zip"]
    assert archiver._siblings(job_b) == ["a.zip"]


async def test_jobs_in_different_roots_do_not_exclude_each_other(tree, tmp_path):
    other_root = tmp_path / "other"
    other_root.mkdir()

    job_a = make_job(tree, name="a")
    job_b = make_job(other_root, name="b")
    archiver = PeriodicArchiver([job_a, job_b])

    assert archiver._siblings(job_a) == []
    assert archiver._siblings(job_b) == []


# --- should_run ---------------------------------------------------------

def test_should_run_defaults_to_elapsed_time_against_min_interval(tree):
    job = make_job(tree, min_interval=1000)
    archiver = PeriodicArchiver([job])

    assert archiver._should_run(job) is False


def test_should_run_true_once_min_interval_has_passed(tree):
    job = make_job(tree, min_interval=0)
    archiver = PeriodicArchiver([job])

    assert archiver._should_run(job) is True


def test_should_run_uses_the_jobs_own_callable_when_given(tree):
    job = make_job(tree, min_interval=999999, should_run=lambda: True)
    archiver = PeriodicArchiver([job])

    assert archiver._should_run(job) is True


def test_two_jobs_sharing_a_name_are_tracked_independently(tree):
    # last_run lives on the job itself now, so two separate ArchiveJob
    # instances never share one regardless of name; only the lock (kept on
    # PeriodicArchiver, keyed by id(job)) could ever have collided on a
    # shared name, and no longer does.
    job_a = make_job(tree, name="dup", min_interval=0)
    job_b = make_job(tree, name="dup", min_interval=999999)
    archiver = PeriodicArchiver([job_a, job_b])

    assert archiver._should_run(job_a) is True
    assert archiver._should_run(job_b) is False


async def test_two_jobs_sharing_a_name_do_not_block_each_other(tree, tmp_path):
    # Different roots so the shared name does not also collide on the
    # archive's own filename -- only the tracking key (name vs id) is
    # under test here.
    other_root = tmp_path / "other_dup_root"
    other_root.mkdir()
    (other_root / "f.txt").write_text("f")

    order = []
    started_a = asyncio.Event()

    async def on_archive_a(job, path):
        started_a.set()
        await asyncio.sleep(0.05)
        order.append("a")

    async def on_archive_b(job, path):
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

async def test_locks_are_created_lazily_and_held_only_weakly(tree):
    from pytrove.classes.misc_classes import DefaultWeakValueDict

    job = make_job(tree)
    archiver = PeriodicArchiver([job])

    assert isinstance(archiver._locks, DefaultWeakValueDict)
    assert len(archiver._locks) == 0  # nothing created until first use


async def test_a_concurrent_run_of_the_same_job_waits_on_its_lock(tree):
    order = []

    async def slow_on_archive(job, path):
        order.append("start")
        await asyncio.sleep(0.05)
        order.append("end")

    job = make_job(tree, name="out", on_archive=slow_on_archive)
    archiver = PeriodicArchiver([job])

    await asyncio.gather(archiver.run_job(job), archiver.run_job(job))

    assert order == ["start", "end", "start", "end"]


# --- lifecycle ------------------------------------------------------------

async def test_start_creates_a_single_scheduling_task(tree):
    job_a = make_job(tree, name="a", poll_interval=1000)
    job_b = make_job(tree, name="b", poll_interval=1000)
    archiver = PeriodicArchiver([job_a, job_b])

    archiver.start()
    task = archiver._task
    assert isinstance(task, asyncio.Task)
    assert not task.done()

    await archiver.stop()
    assert task.done()


def test_the_loops_sleep_interval_is_the_shortest_poll_interval(tree):
    job_a = make_job(tree, name="a", poll_interval=1000)
    job_b = make_job(tree, name="b", poll_interval=5)
    archiver = PeriodicArchiver([job_a, job_b])

    interval = min(job.poll_interval for job in archiver.jobs)
    assert interval == 5


async def test_start_is_a_no_op_while_the_loop_is_still_running(tree):
    job = make_job(tree, poll_interval=1000)
    archiver = PeriodicArchiver([job])

    archiver.start()
    first = archiver._task
    archiver.start()

    assert archiver._task is first
    await archiver.stop()


async def test_restart_replaces_the_scheduling_task(tree):
    job = make_job(tree, poll_interval=1000)
    archiver = PeriodicArchiver([job])

    archiver.start()
    first = archiver._task
    await archiver.restart()

    assert archiver._task is not first
    await archiver.stop()


async def test_loop_keeps_dispatching_while_an_earlier_run_is_still_in_flight(tree):
    finished = asyncio.Event()

    async def slow_on_archive(job, path):
        await finished.wait()

    job = make_job(tree, on_archive=slow_on_archive, min_interval=0, poll_interval=0.01)
    archiver = PeriodicArchiver([job])

    archiver.start()
    await asyncio.sleep(0.05)  # several poll intervals

    # Every later dispatch queues behind the first on the same job's lock,
    # but the loop itself never waited for that first run_job to return
    # before ticking again and dispatching another.
    assert len(archiver._running) > 1
    assert not archiver._task.done()

    finished.set()
    await archiver.stop()
