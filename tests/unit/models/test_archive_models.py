from __future__ import annotations as _annotations

import time
from typing import TYPE_CHECKING

import pytest

from pytrove._internal._stability import _default_stability_check
from pytrove.enums import ArchiveFormat
from pytrove.models import ArchiveJob

if TYPE_CHECKING:
    from pathlib import Path


async def _noop(job: ArchiveJob, path: Path) -> None:
    """Accept the archive and do nothing."""


def test_archive_job_resolves_root_and_format(tmp_path: Path) -> None:
    before = time.monotonic()
    job = ArchiveJob("j", str(tmp_path), lambda: "name", _noop, archive_format="tar.gz")

    assert job.root == tmp_path.resolve()
    assert job.archive_format is ArchiveFormat.TAR_GZ
    assert before <= job.last_run <= time.monotonic()
    assert "last_run" not in repr(job)


def test_archive_path_asks_dest_name_every_time(tmp_path: Path) -> None:
    names = iter(["a", "b"])
    job = ArchiveJob("j", tmp_path, lambda: next(names), _noop)

    assert job.archive_path() == tmp_path.resolve() / "a.zip"
    assert job.archive_path() == tmp_path.resolve() / "b.zip"


def test_last_run_is_not_a_constructor_argument(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        ArchiveJob("j", tmp_path, lambda: "name", _noop, last_run=0.0)  # ty: ignore[unknown-argument]  # Passes the non-init `last_run` on purpose, to prove it is refused.


def test_stability_check_defaults_to_compress_folders_own_default(tmp_path: Path) -> None:
    assert (
        ArchiveJob("j", tmp_path, lambda: "name", _noop).stability_check is _default_stability_check
    )
