"""`files_tools.paths`: `ensure_path`, `resolve_path` and `ensure_dir`."""

from __future__ import annotations as _annotations

import os
from pathlib import Path, PurePosixPath

import pytest

from pytrove.files_tools import ensure_dir, ensure_path, resolve_path, write_file


class _BytesFsPath:
    """An `os.PathLike[bytes]` that is not a `Path`."""

    def __fspath__(self) -> bytes:
        return b"x"


def _umask() -> int:
    old = os.umask(0)
    os.umask(old)
    return old


# --- ensure_path -----------------------------------------------------------


def test_ensure_path_returns_a_path_as_is() -> None:
    path = Path("x")
    assert ensure_path(path) is path
    assert ensure_path("x") == Path("x")


def test_ensure_path_decodes_bytes_paths() -> None:
    assert ensure_path(b"x") == Path("x")
    assert ensure_path(os.fsencode(Path("a") / "b")) == Path("a") / "b"


def test_ensure_path_decodes_a_bytes_pathlike() -> None:
    assert ensure_path(_BytesFsPath()) == Path("x")


def test_ensure_path_converts_a_non_path_str_pathlike() -> None:
    assert ensure_path(PurePosixPath("a/b")) == Path("a/b")


# --- resolve_path ----------------------------------------------------------


def test_resolve_path_is_absolute_and_strict_on_request(tmp_path: Path) -> None:
    assert resolve_path("relative").is_absolute()
    assert resolve_path(tmp_path / "missing") == tmp_path.resolve() / "missing"

    with pytest.raises(FileNotFoundError):
        resolve_path(tmp_path / "missing", strict=True)


def test_resolve_path_takes_str_and_bytes(tmp_path: Path) -> None:
    assert resolve_path(str(tmp_path)) == tmp_path.resolve()
    assert resolve_path(os.fsencode(tmp_path)) == tmp_path.resolve()


# --- ensure_dir ------------------------------------------------------------


def test_ensure_dir_makes_the_directory_and_hands_the_path_back(tmp_path: Path) -> None:
    target = tmp_path / "logs"

    got = ensure_dir(target)

    assert got == target
    assert got.is_dir()


def test_ensure_dir_makes_every_missing_level(tmp_path: Path) -> None:
    # parents defaults to True where mkdir's own default is False.
    got = ensure_dir(tmp_path / "a" / "b" / "c")

    assert got.is_dir()
    assert (tmp_path / "a" / "b").is_dir()


def test_ensure_dir_for_a_file_makes_the_directory_above_it(tmp_path: Path) -> None:
    target = tmp_path / "out" / "2024" / "log.txt"

    got = ensure_dir(target, for_file=True)

    assert got == target
    assert got.parent.is_dir()
    # the file itself is not created -- it is the caller's to write
    assert not got.exists()


def test_a_path_from_ensure_dir_is_writable_straight_away(tmp_path: Path) -> None:
    # The reason it returns the argument rather than the directory: it
    # composes with the writers, in one expression and no temporary.
    write_file(
        ensure_dir(tmp_path / "deep" / "nest" / "note.txt", for_file=True), "hello", fsync=False
    )

    assert (tmp_path / "deep" / "nest" / "note.txt").read_text(encoding="utf-8") == "hello"


def test_ensure_dir_is_content_with_a_directory_that_is_already_there(tmp_path: Path) -> None:
    target = ensure_dir(tmp_path / "twice")

    assert ensure_dir(target) == target


def test_ensure_dir_passes_exist_ok_through(tmp_path: Path) -> None:
    target = ensure_dir(tmp_path / "once")

    with pytest.raises(FileExistsError):
        ensure_dir(target, exist_ok=False)


def test_ensure_dir_passes_parents_through(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ensure_dir(tmp_path / "no" / "such" / "parent", parents=False)


def test_a_file_standing_where_a_directory_was_asked_for_is_not_forgiven(tmp_path: Path) -> None:
    # exist_ok forgives a directory and nothing else, which is right: the
    # caller asked for a directory there and there is not one.
    occupied = tmp_path / "occupied"
    occupied.write_text("i am a file", encoding="utf-8")

    with pytest.raises(FileExistsError):
        ensure_dir(occupied)


def test_ensure_dir_takes_a_string_and_returns_a_path(tmp_path: Path) -> None:
    got = ensure_dir(str(tmp_path / "from_str"))

    assert isinstance(got, Path)
    assert got.is_dir()


def test_ensure_dir_does_not_resolve_what_it_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Relative stays relative: the caller gets back what it passed in, and
    # reaches for resolve_path when it wants an absolute one.
    monkeypatch.chdir(tmp_path)

    got = ensure_dir("relative/here")

    assert got == Path("relative/here")
    assert not got.is_absolute()
    assert (tmp_path / "relative" / "here").is_dir()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_ensure_dir_passes_mode_through(tmp_path: Path) -> None:
    got = ensure_dir(tmp_path / "narrow", mode=0o700)

    assert got.stat().st_mode & 0o777 == 0o700 & ~_umask()


def test_a_keyword_mkdir_does_not_take_is_refused_by_name(tmp_path: Path) -> None:
    # Unpack is a static check and does nothing at runtime, so the runtime
    # answer comes from mkdir -- which still names the offending keyword.
    with pytest.raises(TypeError, match="parent"):
        ensure_dir(tmp_path / "typo", parent=True)  # type: ignore[call-arg]  # The wrong keyword is the point.
