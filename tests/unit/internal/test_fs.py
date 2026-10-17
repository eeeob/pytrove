import os
import shutil
import stat
import subprocess
import sys

import pytest

from pytrove import remove_path
from pytrove._internal import _fs


def _own_islink(path):
    """What _is_link means, spelled out here so the tests own a definition.

    A symlink anywhere, plus a Windows junction, which is a directory
    reparse point carrying IO_REPARSE_TAG_MOUNT_POINT. _files_tools gets
    this from shutil where it can and writes it out where it cannot; this
    is the version the tests compare against, so a stdlib that answers
    differently is a red test rather than a quiet change of behaviour.
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


def _make_junction(link, target):
    """A Windows junction at `link`, or None where one cannot be made."""

    if os.name != "nt":
        return None

    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                          capture_output=True)

    return link if done.returncode == 0 and link.exists() else None


def test_is_link_agrees_with_the_definition_on_every_kind_of_path(tmp_path):
    # The four shapes that reach the removers, whichever way _files_tools
    # resolved _is_link on this interpreter: shutil's own on 3.10-3.12, a
    # wrapper around it on 3.13-3.14, the local fallback anywhere else.
    a_dir = tmp_path / "d"
    a_dir.mkdir()
    a_file = tmp_path / "f.txt"
    a_file.write_text("x", encoding="utf-8")
    missing = tmp_path / "ghost"

    for path in (a_dir, a_file, missing, tmp_path):
        assert bool(_fs._is_link(path)) == _own_islink(path), path


def test_a_missing_path_is_not_a_link(tmp_path):
    # Not an error either: the removers ask this about paths that may well
    # have gone, and every branch of _is_link swallows the OSError itself.
    assert not _fs._is_link(tmp_path / "never")
    assert not _fs._is_dir(tmp_path / "never")


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows reparse point")
def test_a_junction_is_a_link_and_is_not_a_plain_directory(tmp_path):
    # The case the whole predicate exists for. A junction reports is_dir()
    # True and is_symlink() False, so `is_dir() and not is_symlink()` walks
    # into one -- measured on 3.10 through 3.14, os.path.islink() is False
    # for a junction on every one of them, and os.path.isjunction() only
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
    remove_path(link)

    assert not link.exists()
    assert (target / "inside.txt").read_text(encoding="utf-8") == "kept"


@pytest.mark.parametrize("tag, link, plain_dir", [
    (0, False, True),                                   # an ordinary directory
    (0xA0000003, True, False),                          # IO_REPARSE_TAG_MOUNT_POINT
    (0x9000001A, False, True),                          # OneDrive files-on-demand
    (0x80000013, False, True),                          # IO_REPARSE_TAG_DEDUP
    (0x8000001B, False, True),                          # APPEXECLINK
])
@pytest.mark.skipif(os.name != "nt", reason="reparse tags are Windows-only")
def test_only_a_junction_tag_counts_as_a_link(monkeypatch, tag, link, plain_dir):
    # Windows hands out far more reparse tags than the three `stat` names,
    # and all but the junction mark a real file or a real directory that is
    # merely stored unusually. Treating any tag as a link -- which this
    # briefly did -- would send a cloud-backed directory to unlink and leave
    # it standing, since remove_paths splits on _is_dir before
    # remove_folders is ever reached.
    #
    # A placeholder cannot be created on demand, so the stat is faked. It
    # carries st_file_attributes as well as the tag, because shutil's own
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


@pytest.mark.skipif(os.name != "nt", reason="reparse tags are Windows-only")
def test_the_junction_tag_is_the_one_shutil_uses():
    # _is_link is shutil's own _rmtree_islink where the shape allows it, so
    # this holds by construction there. It is asserted for the fallback,
    # which writes the constant out: rmtree acts on shutil's answer, and a
    # remover that disagreed with it would decline to follow a link that
    # rmtree then followed.
    assert _own_islink.__doc__  # the definition above is the one compared to
    assert stat.IO_REPARSE_TAG_MOUNT_POINT == 0xA0000003


def test_is_link_is_resolved_from_shutil_where_the_shape_is_known():
    # The version gate in _files_tools claims 3.10 through 3.14. Two shapes
    # live in that range -- _rmtree_islink(path) up to 3.12 and
    # _rmtree_islink(st) from 3.13 -- and the gate has to have picked the
    # right one, because picking the wrong one raises AttributeError at the
    # first call rather than at the import.
    if not (3, 10) <= sys.version_info[:2] <= (3, 14):
        pytest.skip("outside the range the gate claims")

    assert hasattr(shutil, "_rmtree_islink"), (
        "the gate imports this unconditionally inside its range"
    )

    # Whichever shape it is, _is_link answers a path without raising.
    assert _fs._is_link(__file__) == _own_islink(__file__)


def test_is_link_without_file_attributes_is_os_path_islink(monkeypatch: pytest.MonkeyPatch) -> None:
    # Off Windows `os.lstat` reports no file attributes, so there is no
    # junction to look for and `_is_link` is `os.path.islink`.
    seen: list[str] = []
    monkeypatch.setattr(_fs, "_HAS_FILE_ATTRIBUTES", False)
    monkeypatch.setattr(os.path, "islink", lambda path: seen.append(path) or True)

    assert _fs._is_link("anything") is True
    assert seen == ["anything"]


def test_is_dir_is_the_inverse_of_is_link_for_a_directory(tmp_path):
    a_dir = tmp_path / "d"
    a_dir.mkdir()
    a_file = tmp_path / "f.txt"
    a_file.write_text("x", encoding="utf-8")

    assert _fs._is_dir(a_dir) is True
    assert _fs._is_dir(a_file) is False
    assert _fs._is_dir(tmp_path / "ghost") is False
