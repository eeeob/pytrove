from __future__ import annotations as _annotations

import io
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from pytrove.archive_tools._internal import backends, common, stable, writers
from pytrove.archive_tools._internal.extractor import _Extractor
from pytrove.archive_tools._internal.rules import _Filter
from pytrove.enums import ArchiveFormat
from pytrove.errors import ValidationError


class _Entry:
    """A stand-in for `os.DirEntry`, with only a name."""

    def __init__(self, name: str) -> None:
        """Store `name`."""
        self.name = name

    def stat(self) -> Any:
        """Fail like an unreadable entry."""
        raise OSError


def test_constants() -> None:
    assert common._LINK_MAX == 4096
    assert common._NT is (os.name == "nt")
    assert dict(common._SUFFIXES)[".tgz"] is ArchiveFormat.TAR_GZ


@pytest.mark.parametrize(("name", "fmt"), [
    ("a.ZIP", ArchiveFormat.ZIP),
    ("a.tar.zst", ArchiveFormat.TAR_ZST),
    ("a.tar.gz", ArchiveFormat.TAR_GZ),
    ("a.tgz", ArchiveFormat.TAR_GZ),
    ("a.rar", None),
])
def test_format_from_suffix(name: str, fmt: ArchiveFormat | None) -> None:
    assert common._format_from_suffix(name) is fmt


def test_split_workers_reads_a_count_or_a_pool() -> None:
    assert common._split_workers(None, "x") == (None, None)
    assert common._split_workers(3, "x") == (3, None)
    assert common._split_workers(-1, "x") == (os.cpu_count() or 1, None)

    with ThreadPoolExecutor(1) as pool:
        assert common._split_workers(pool, "x") == (None, pool)

    with pytest.raises(ValidationError, match="who: workers"):
        common._split_workers(True, "who")


def test_is_hidden_reads_the_name_and_survives_an_unreadable_entry() -> None:
    assert common._is_hidden("x", _Entry(".git"))
    assert not common._is_hidden("x", _Entry("src"))
    assert not common._is_hidden("x", None)


def test_temp_file_rule_matches_only_the_temp_file_in_its_folder() -> None:
    rule = common._temp_file_rule("out/", ".b.zip.")
    assert rule("out/.b.zip.abc123.tmp", None)
    assert not rule("other/.b.zip.abc123.tmp", None)
    assert not rule("out/.b.zip.notes", None)
    assert not rule("out/deep/.b.zip.x.tmp", None)


def test_require_zstd_raises_without_any_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends, "std_zstd", None)
    monkeypatch.setattr(backends, "zstandard", None)

    with pytest.raises(ImportError):
        common._require_zstd()


def test_require_zstd_passes_with_a_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends, "zstandard", object())
    assert common._require_zstd() is None


def test_backends_expose_every_name() -> None:
    assert set(backends.__all__) == {"GitIgnoreSpec", "PathSpec", "WZip", "std_zstd", "zstandard"}


def test_stable_source_reads_directly_when_not_guarded(tmp_path: Path) -> None:
    target = tmp_path / "f"
    target.write_bytes(b"x")
    skip, tmp, before = stable._stable_source(str(target), 0, lambda st, p: True)
    assert (skip, tmp) == (False, None)
    assert before.st_size == 1


def test_stable_source_copies_a_guarded_file(tmp_path: Path) -> None:
    target = tmp_path / "f"
    target.write_bytes(b"data")
    skip, tmp, _ = stable._stable_source(str(target), 2, lambda st, p: True)

    try:
        assert skip is False
        assert Path(tmp).read_bytes() == b"data"
    finally:
        os.unlink(tmp)


def test_stable_source_skips_a_file_that_cannot_be_copied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "f"
    target.write_bytes(b"x")

    def boom(path: str, retries: int) -> Any:
        """Fail like a vanished file."""
        raise OSError

    monkeypatch.setattr(stable, "_read_stable", boom)
    assert stable._stable_source(str(target), 1, lambda st, p: True)[:2] == (True, None)


def test_stable_source_of_a_missing_file_is_read_directly(tmp_path: Path) -> None:
    assert stable._stable_source(str(tmp_path / "gone"), 3, lambda st, p: True) == (False, None, None)


def test_read_stable_refuses_a_negative_retry_count(tmp_path: Path) -> None:
    target = tmp_path / "f"
    target.write_bytes(b"x")

    with pytest.raises(ValueError, match="retries must be at least 0"):
        stable._read_stable(str(target), -1)


def test_tar_reader_refuses_tar_zst_without_a_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "a.tar.zst"
    src.write_bytes(b"")
    monkeypatch.setattr(backends, "std_zstd", None)
    monkeypatch.setattr(backends, "zstandard", None)
    extractor = _Extractor(src, tmp_path / "out", _Filter.from_rules((), ()))

    with pytest.raises(RuntimeError, match="needs a zstd backend"):
        extractor._tar(ArchiveFormat.TAR_ZST)


def test_tar_writer_refuses_tar_zst_without_a_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends, "std_zstd", None)
    monkeypatch.setattr(backends, "zstandard", None)

    with pytest.raises(RuntimeError, match="needs a zstd backend"):
        writers._write_tar((), io.BytesIO(), ArchiveFormat.TAR_ZST, None, None, None, 0, lambda st, p: False)
