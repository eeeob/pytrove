from __future__ import annotations as _annotations

import os
import stat
import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from pytrove import remove_paths
from pytrove._internal import _fs

if TYPE_CHECKING:
    from pathlib import Path


def _own_islink(path: str | os.PathLike[str]) -> bool:
    """What `_is_link` means, spelled out here so the tests own a definition.

    A symlink anywhere, plus a Windows junction, which is a directory
    reparse point carrying `IO_REPARSE_TAG_MOUNT_POINT`. A stdlib that
    answered differently is a red test rather than a quiet change of behaviour.
    """

    try:
        st = os.lstat(path)
    except OSError:
        return False

    if stat.S_ISLNK(st.st_mode):
        return True

    return bool(
        getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        and getattr(st, "st_reparse_tag", 0) == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)
    )


def _make_junction(link: Path, target: Path) -> Path | None:
    """A Windows junction at `link`, or None where one cannot be made."""

    if os.name != "nt":
        return None

    done = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False
    )  # a failure is read from `returncode`

    return link if done.returncode == 0 and link.exists() else None


def test_is_link_agrees_with_the_definition_on_every_kind_of_path(tmp_path: Path) -> None:
    # The four plain shapes that reach the removers; links are tested below.
    a_dir = tmp_path / "d"
    a_dir.mkdir()
    a_file = tmp_path / "f.txt"
    a_file.write_text("x", encoding="utf-8")
    missing = tmp_path / "ghost"

    for path in (a_dir, a_file, missing, tmp_path):
        assert bool(_fs._is_link(path)) == _own_islink(path), path


def test_a_missing_path_is_not_a_link(tmp_path: Path) -> None:
    # Not an error either: the removers ask this about paths that may well
    # have gone, and every branch of `_is_link` swallows the `OSError` itself.
    assert not _fs._is_link(tmp_path / "never")
    assert not _fs._is_dir(tmp_path / "never")


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows reparse point")
def test_a_junction_is_a_link_and_is_not_a_plain_directory(tmp_path: Path) -> None:
    # The case the whole predicate exists for. A junction reports `is_dir()`
    # True and `is_symlink()` False, so `is_dir() and not is_symlink()` walks
    # into one -- measured on 3.10 through 3.14, `os.path.islink()` is False
    # for a junction on every one of them, and `os.path.isjunction()` only
    # exists from 3.12.
    target = tmp_path / "real"
    target.mkdir()
    (target / "inside.txt").write_text("kept", encoding="utf-8")

    link = _make_junction(tmp_path / "j", target)

    if link is None:
        pytest.skip("mklink /J is not available here")

    assert os.path.islink(link) is False, "the easy spelling would have said no"
    assert _fs._is_link(link)
    assert _fs._is_dir(link) is False
    assert _fs._is_dir(target) is True

    # And removing it takes the link, never the tree it names.
    remove_paths(link)

    assert not link.exists()
    assert (target / "inside.txt").read_text(encoding="utf-8") == "kept"


@pytest.mark.parametrize(
    "tag, link, plain_dir",
    [
        (0, False, True),  # an ordinary directory
        (0xA0000003, True, False),  # IO_REPARSE_TAG_MOUNT_POINT
        (0x9000001A, False, True),  # OneDrive files-on-demand
        (0x80000013, False, True),  # IO_REPARSE_TAG_DEDUP
        (0x8000001B, False, True),  # APPEXECLINK
    ],
)
@pytest.mark.skipif(os.name != "nt", reason="reparse tags are Windows-only")
def test_only_a_junction_tag_counts_as_a_link(
    monkeypatch: pytest.MonkeyPatch, tag: int, link: bool, plain_dir: bool
) -> None:
    # Windows hands out far more reparse tags than the three `stat` names,
    # and all but the junction mark a real file or a real directory that is
    # merely stored unusually. Treating any tag as a link -- which this
    # briefly did -- would send a cloud-backed directory to unlink and leave
    # it standing, since `remove_paths` splits on `_is_dir` before
    # `remove_folders` is ever reached.
    #
    # A placeholder cannot be created on demand, so the stat is faked. It
    # carries `st_file_attributes` as well as the tag, because shutil's own
    # version reads both and this has to be a stat either implementation
    # can answer.
    class Faked:
        st_mode = stat.S_IFDIR | 0o755
        st_file_attributes = stat.FILE_ATTRIBUTE_DIRECTORY | (
            stat.FILE_ATTRIBUTE_REPARSE_POINT if tag else 0
        )
        st_reparse_tag = tag

    monkeypatch.setattr(os, "lstat", lambda path: Faked())

    assert bool(_fs._is_link("anything")) is link
    assert _fs._is_dir("anything") is plain_dir


def _make_symlink(link: Path, target: Path) -> Path:
    """A symlink at `link` to `target`, skipping the test where the OS refuses one."""
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (
        OSError,
        NotImplementedError,
    ) as exc:  # Windows without the privilege or Developer Mode.
        pytest.skip(f"cannot create a symlink here: {exc}")
    return link


def test_a_symlink_to_a_file_is_a_link_and_not_a_directory(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x", encoding="utf-8")
    link = _make_symlink(tmp_path / "l", target)

    assert _fs._is_link(link) is True
    assert _fs._is_dir(link) is False


def test_a_symlink_to_a_directory_is_a_link_and_not_a_directory(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = _make_symlink(tmp_path / "l", target)

    assert os.path.isdir(link), "following it would have said yes"
    assert _fs._is_link(link) is True
    assert _fs._is_dir(link) is False
    assert _fs._is_dir(target) is True
    assert _fs._is_link(target) is False


def test_a_dangling_symlink_is_still_a_link(tmp_path: Path) -> None:
    link = _make_symlink(tmp_path / "l", tmp_path / "gone")

    assert _fs._is_link(link) is True
    assert _fs._is_dir(link) is False


def test_has_file_attributes_reflects_the_stat_result() -> None:
    assert _fs._HAS_FILE_ATTRIBUTES == hasattr(os.stat_result, "st_file_attributes")


def test_is_link_without_file_attributes_is_os_path_islink(monkeypatch: pytest.MonkeyPatch) -> None:
    # Off Windows `os.lstat` reports no file attributes, so there is no
    # junction to look for and `_is_link` is `os.path.islink`.
    seen: list[str] = []
    monkeypatch.setattr(_fs, "_HAS_FILE_ATTRIBUTES", False)
    monkeypatch.setattr(os.path, "islink", lambda path: seen.append(path) or True)

    assert _fs._is_link("anything") is True
    assert seen == ["anything"]


def test_is_dir_is_the_inverse_of_is_link_for_a_directory(tmp_path: Path) -> None:
    a_dir = tmp_path / "d"
    a_dir.mkdir()
    a_file = tmp_path / "f.txt"
    a_file.write_text("x", encoding="utf-8")

    assert _fs._is_dir(a_dir) is True
    assert _fs._is_dir(a_file) is False
    assert _fs._is_dir(tmp_path / "ghost") is False


def test_copy_buf_is_one_mebibyte() -> None:
    assert _fs._COPY_BUF == 1 << 20


@pytest.mark.parametrize(
    "mode, attributes, tag, link",
    [
        (stat.S_IFREG, 0, 0, False),
        (stat.S_IFDIR, 0, 0, False),
        (stat.S_IFLNK, 0, 0, True),
        (stat.S_IFDIR, 0x400, 0xA0000003, True),  # FILE_ATTRIBUTE_REPARSE_POINT, a junction
        (stat.S_IFDIR, 0x400, 0x9000001A, False),  # a reparse point that is not a junction
        (stat.S_IFDIR, 0, 0xA0000003, False),  # a junction tag without the reparse attribute
    ],
)
def test_stat_is_link_reads_the_mode_and_the_junction_tag(
    monkeypatch: pytest.MonkeyPatch, mode: int, attributes: int, tag: int, link: bool
) -> None:
    # The constants are Windows-only, so they are given here for every platform.
    monkeypatch.setattr(_fs, "_HAS_FILE_ATTRIBUTES", True)
    monkeypatch.setattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400, raising=False)
    monkeypatch.setattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003, raising=False)
    st = SimpleNamespace(st_mode=mode, st_file_attributes=attributes, st_reparse_tag=tag)

    assert _fs._stat_is_link(cast("os.stat_result", st)) is link


def test_stat_is_link_reads_only_the_mode_without_file_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Off Windows there are no attribute fields to read; touching one would raise.
    monkeypatch.setattr(_fs, "_HAS_FILE_ATTRIBUTES", False)

    assert _fs._stat_is_link(cast("os.stat_result", SimpleNamespace(st_mode=stat.S_IFLNK)))
    assert not _fs._stat_is_link(cast("os.stat_result", SimpleNamespace(st_mode=stat.S_IFDIR)))


def test_is_dir_takes_a_single_lstat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = os.lstat
    calls: list[str] = []

    def lstat(path: str | os.PathLike[str]) -> os.stat_result:
        calls.append(os.fspath(path))
        return real(path)

    monkeypatch.setattr(os, "lstat", lstat)

    assert _fs._is_dir(tmp_path) is True
    assert calls == [os.fspath(tmp_path)]
