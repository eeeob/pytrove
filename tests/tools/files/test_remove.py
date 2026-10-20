"""`files_tools.remove`: `remove_files`, `remove_folders`, `remove_paths` and their aliases."""

from __future__ import annotations as _annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pytrove.files_tools import (
    remove_file,
    remove_files,
    remove_folder,
    remove_folders,
    remove_path,
    remove_paths,
)


def _dir_link(link: Path, target: Path) -> str | None:
    """Point `link` at directory `target`, however this platform can.

    A symlink where the account may make one, and a Windows junction
    otherwise -- an ordinary Windows account holds no
    SeCreateSymbolicLinkPrivilege, and a junction needs none. The two are
    the same hazard for this code and differ in exactly the way that
    matters: a junction reports neither islink() nor is_symlink().
    """
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        if sys.platform != "win32":
            return None
    else:
        return "symlink"

    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False)

    return "junction" if made.returncode == 0 else None


@pytest.fixture
def linked(tmp_path: Path) -> tuple[Path, Path]:
    """A link to a directory that holds something worth not losing."""
    target = tmp_path / "TARGET"
    target.mkdir()
    (target / "precious.txt").write_text("precious", encoding="utf-8")

    link = tmp_path / "link"

    if _dir_link(link, target) is None:
        pytest.skip("cannot link to a directory here")

    return link, target


def test_the_short_names_are_the_same_functions() -> None:
    assert remove_file is remove_files
    assert remove_folder is remove_folders
    assert remove_path is remove_paths


@pytest.mark.parametrize("remove", [remove_file, remove_folder, remove_path])
def test_a_link_to_a_directory_is_removed_and_its_target_is_not(
    linked: tuple[Path, Path], remove: Callable[..., Any],
) -> None:
    # The link is one entry and is removed as one. Following it would take
    # out a tree nobody named -- and a junction is the case that catches a
    # check written as is_dir(), since it reports neither islink() nor
    # is_symlink() while answering is_dir() True.
    link, target = linked

    remove(link)

    assert not os.path.lexists(link)
    assert (target / "precious.txt").read_text(encoding="utf-8") == "precious"


@pytest.mark.parametrize("remove", [remove_file, remove_folder, remove_path])
def test_a_path_that_was_never_there_is_not_a_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, remove: Callable[..., Any],
) -> None:
    # Making sure a path is gone, and it is gone. Calling twice must not
    # be an error either.
    with caplog.at_level("WARNING"):
        remove(tmp_path / "ghost")

    assert caplog.text == ""


def test_removing_a_tree_takes_everything_under_it(tmp_path: Path) -> None:
    deep = tmp_path / "tree" / "a" / "b"
    deep.mkdir(parents=True)
    (deep / "leaf.txt").write_text("leaf", encoding="utf-8")

    remove_path(tmp_path / "tree")

    assert not (tmp_path / "tree").exists()


def test_remove_files_returns_what_it_actually_removed(tmp_path: Path) -> None:
    one = tmp_path / "one.txt"
    two = tmp_path / "two.txt"
    one.write_text("1", encoding="utf-8")
    two.write_text("2", encoding="utf-8")

    assert remove_file(one, two) == [one, two]
    assert not one.exists() and not two.exists()


def test_a_missing_path_is_success_and_is_not_in_the_result(tmp_path: Path) -> None:
    # These are for making sure a path is gone, and one that was never
    # there is gone. Calling twice is not an error.
    gone = tmp_path / "ghost"
    real = tmp_path / "real.txt"
    real.write_text("x", encoding="utf-8")

    assert remove_file(gone, real) == [real]
    assert remove_file(gone, real) == []


def test_the_same_path_twice_is_one_unlink(tmp_path: Path) -> None:
    # Flattened to Path first and de-duplicated after, so the two spellings
    # of one file are one entry -- they compare unequal as they arrive.
    target = tmp_path / "a.txt"
    target.write_text("x", encoding="utf-8")

    assert remove_file(str(target), target, [target]) == [target]


def test_a_directory_handed_to_remove_file_raises_by_default(tmp_path: Path) -> None:
    # os.unlink refuses a real directory, and refusing is right: remove_file
    # removes one entry, and a directory is however much someone put in it.
    target = tmp_path / "a_dir"
    target.mkdir()

    with pytest.raises(OSError):
        remove_file(target)

    assert target.is_dir()


def test_return_exc_collects_the_refusal_and_carries_on(tmp_path: Path) -> None:
    # Raising on the first would leave the rest untouched, which is not
    # what a cleanup wants -- one stubborn file should not cost the other
    # nine.
    one = tmp_path / "one.txt"
    two = tmp_path / "two.txt"
    one.write_text("1", encoding="utf-8")
    two.write_text("2", encoding="utf-8")
    stubborn = tmp_path / "a_dir"
    stubborn.mkdir()

    result = remove_file(one, stubborn, two, return_exc=True)

    assert not one.exists() and not two.exists()
    assert stubborn.is_dir()
    assert [type(r) is not OSError and isinstance(r, OSError) for r in result].count(True) == 1
    assert result[0] == one and result[2] == two


def test_remove_folders_returns_what_it_actually_removed(tmp_path: Path) -> None:
    d1 = tmp_path / "d1"
    d2 = tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    (d1 / "inside.txt").write_text("x", encoding="utf-8")

    assert remove_folder(d1, d2) == [d1, d2]
    assert not d1.exists() and not d2.exists()


def test_remove_folders_treats_a_missing_directory_as_success(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()

    assert remove_folder(tmp_path / "ghost", real) == [real]
    assert remove_folder(tmp_path / "ghost") == []


def test_remove_folders_refuses_a_file_by_default(tmp_path: Path) -> None:
    # Only a real directory is something rmtree can walk -- a file handed
    # here is refused rather than resolved into one.
    target = tmp_path / "a_file.txt"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(OSError):
        remove_folder(target)

    assert target.is_file()


def test_remove_folders_return_exc_collects_and_carries_on(tmp_path: Path) -> None:
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    stubborn = tmp_path / "a_file.txt"
    stubborn.write_text("x", encoding="utf-8")

    result = remove_folder(one, stubborn, two, return_exc=True)

    assert not one.exists() and not two.exists()
    assert stubborn.is_file()
    assert isinstance(result[1], OSError)
    assert result[0] == one and result[2] == two


def test_remove_folders_log_exc_names_the_directory(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    target = tmp_path / "a_file.txt"
    target.write_text("x", encoding="utf-8")

    with caplog.at_level("WARNING"):
        remove_folder(target, return_exc=True, log_exc=True)

    record = caplog.records[0]

    assert record.levelname == "ERROR"
    assert record.exc_info is not None
    assert record.getMessage() == f"remove_folders: could not remove {target}"


def test_remove_folders_takes_the_junction_and_not_the_tree(linked: tuple[Path, Path]) -> None:
    # rmtree refuses a reparse point outright, since the kernel counts it
    # as a directory -- the onerror hook is what turns that refusal into an
    # unlink of the link itself, never of what it points at.
    link, target = linked

    remove_folder(link)

    assert not os.path.lexists(link)
    assert (target / "precious.txt").read_text(encoding="utf-8") == "precious"


def test_remove_paths_dispatches_by_kind(tmp_path: Path) -> None:
    a_dir = tmp_path / "a_dir"
    a_dir.mkdir()
    (a_dir / "inside.txt").write_text("x", encoding="utf-8")
    a_file = tmp_path / "a_file.txt"
    a_file.write_text("x", encoding="utf-8")

    assert remove_path(a_dir, a_file) == [a_dir, a_file]
    assert not a_dir.exists() and not a_file.exists()


def test_remove_paths_forwards_return_exc_and_log_exc(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # What blocks a removal differs by platform: Windows refuses to unlink a
    # file that is still open, POSIX does not (the open handle stays valid
    # against the now-unlinked inode) -- so `held` is made unremovable the
    # way each platform actually enforces it, an open handle on Windows and
    # a write-less parent directory on POSIX.
    good = tmp_path / "good.txt"
    good.write_text("x", encoding="utf-8")
    held = tmp_path / "held"
    held.mkdir()
    (held / "open.txt").write_text("x", encoding="utf-8")

    handle = open(held / "open.txt", "w", encoding="utf-8") if os.name == "nt" else None

    if handle is None:
        held.chmod(0o555)  # no write bit: nothing inside can be unlinked

    try:
        with caplog.at_level("WARNING"):
            result = remove_path(good, held, return_exc=True, log_exc=True)
    finally:
        if handle is not None:
            handle.close()
        else:
            held.chmod(0o755)  # restored so tmp_path's own cleanup can remove it

    assert result[0] == good
    assert isinstance(result[1], OSError)
    assert "remove_folders: could not remove" in caplog.text


def test_every_exception_carries_its_own_path(tmp_path: Path) -> None:
    # A list of exceptions is read somewhere else entirely, so each one has
    # to say what it is about. `filename` is the slot OSError.__str__
    # reads, which puts the path in the message rather than only on the
    # object.
    stubborn = tmp_path / "a_dir"
    stubborn.mkdir()
    other = tmp_path / "b_dir"
    other.mkdir()

    a, b = remove_file(stubborn, other, return_exc=True)

    assert isinstance(a, OSError) and isinstance(b, OSError)
    assert a.filename == str(stubborn)
    assert b.filename == str(other)

    # OSError.__str__ writes the filename with repr(), which doubles every
    # separator on Windows -- so the message is searched for what it really
    # holds rather than for the path as the caller spelled it.
    assert repr(str(stubborn)) in str(a)


def test_the_path_on_the_exception_is_the_normalised_one(tmp_path: Path) -> None:
    # os.unlink fills `filename` with the path exactly as it was handed
    # over -- a trailing slash and all -- and this rewrites it from the
    # Path, so a hundred exceptions read in one spelling.
    stubborn = tmp_path / "a_dir"
    stubborn.mkdir()

    odd = str(stubborn) + "/"
    exc = remove_file(odd, return_exc=True)[0]

    assert isinstance(exc, OSError)
    assert exc.filename == str(stubborn)
    assert not exc.filename.endswith("/")


def test_log_exc_names_the_path_and_brings_the_traceback(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # log.exception, so it lands at ERROR carrying the traceback: it is
    # reporting a failure nobody else is going to see, since return_exc
    # means it was swallowed here.
    target = tmp_path / "a_dir"
    target.mkdir()

    with caplog.at_level("WARNING"):
        remove_file(target, return_exc=True, log_exc=True)

    record = caplog.records[0]

    assert record.levelname == "ERROR"
    assert record.exc_info is not None, "the traceback is the point of log.exception"
    assert record.getMessage() == f"remove_files: could not remove {target}"

    # and the operating system's own words come with it, spelled the way it
    # spells them -- os.unlink() on a directory is refused as a permission
    # problem on Windows, but reported for what it specifically is on POSIX.
    assert ("PermissionError" if os.name == "nt" else "IsADirectoryError") in caplog.text
    assert ("[WinError " if os.name == "nt" else "[Errno ") in caplog.text


def test_log_exc_says_nothing_for_an_exception_that_is_raised(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    # Same rule as safe_call: one that propagates was never handled here,
    # so logging it as well would report one failure twice under two
    # different owners.
    target = tmp_path / "a_dir"
    target.mkdir()

    with caplog.at_level("WARNING"), pytest.raises(OSError):
        remove_file(target, log_exc=True)

    assert caplog.text == ""


def test_a_raised_exception_is_annotated_too(tmp_path: Path) -> None:
    # The path goes on before the raise, not after the decision to collect,
    # so a caller that catches one is handed the same exception a caller
    # that collects it would have got.
    target = tmp_path / "a_dir"
    target.mkdir()

    with pytest.raises(OSError) as caught:
        remove_file(str(target) + "/")

    assert caught.value.filename == str(target)


def test_the_removers_take_any_nesting_of_paths(tmp_path: Path) -> None:
    made = []

    for name in ("a.txt", "b.txt", "c.txt"):
        path = tmp_path / name
        path.write_text("x", encoding="utf-8")
        made.append(path)

    remove_path(made[0], [made[1], (made[2],)])

    assert not any(p.exists() for p in made)
