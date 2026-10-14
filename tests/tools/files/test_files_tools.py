import glob
import inspect
import json
import os
import shutil
import stat
import subprocess
import sys

import pytest

from pathlib import Path

from pytrove import (atomic_write, ensure_dir, load_json, remove_file,
                     remove_folder, remove_path, save_json, truncate_file,
                     write_file)
import pytrove._files_tools as internals
from pytrove._files_tools import _MkdirOptions
from pytrove.enums import TruncateSide
from pytrove.errors import ValidationError


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "data.json"
    save_json(path, {"a": 1, "b": [1, 2, 3]})
    assert load_json(path) == {"a": 1, "b": [1, 2, 3]}


def test_save_json_leaves_no_temp_file_behind(tmp_path):
    path = tmp_path / "data.json"
    save_json(path, {"a": 1})
    assert glob.glob(str(path) + "*.tmp") == []


def test_load_json_missing_file_returns_default(tmp_path):
    path = tmp_path / "missing.json"
    assert load_json(path, default={"fallback": True}) == {"fallback": True}


def test_load_json_corrupted_file_raises_decode_error(tmp_path):
    # By design, only a missing file falls back to `default` -- a corrupted/
    # truncated file (e.g. from a prior interrupted write, now prevented by
    # save_json()'s atomic replace) raises loudly instead of silently
    # returning `default` and masking the corruption.
    path = tmp_path / "corrupted.json"
    path.write_text("{not valid json!!!", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_json(path, default={"fallback": True})


def test_load_json_empty_file_raises_decode_error(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_json(path, default={"fallback": True})


# The failure is triggered by data no serialiser can encode, rather than by
# monkeypatching json.dumps: save_json hands the work to orjson whenever the
# `fastjson` extra is installed and the kwargs allow it, so patching one
# serialiser would silently stop testing anything on that path.
class _Unserialisable:
    pass


def test_save_json_cleans_up_temp_file_on_failure(tmp_path):
    path = tmp_path / "data.json"

    with pytest.raises(TypeError):
        save_json(path, {"a": _Unserialisable()})

    assert glob.glob(str(path) + "*.tmp") == []
    assert not path.exists()


def test_save_json_does_not_corrupt_existing_file_on_failure(tmp_path):
    path = tmp_path / "data.json"
    save_json(path, {"a": 1})

    with pytest.raises(TypeError):
        save_json(path, {"a": _Unserialisable()})

    # The atomic replace never happened, so the original content must survive.
    assert load_json(path) == {"a": 1}


# ---------------------------------------------------------------------
# truncate_file
# ---------------------------------------------------------------------

#: Content with no repeating window, so a wrongly ordered or wrongly cut
#: part cannot pass a comparison by accident.
_DATA = bytes(range(256)) * 40          # 10240 bytes


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "app.log"
    path.write_bytes(_DATA)
    return path


def test_truncate_keeps_the_head_and_drops_the_tail(sample):
    assert truncate_file(sample, 1000, cut=TruncateSide.TAIL) == sample
    assert sample.read_bytes() == _DATA[:1000]


def test_truncate_keeps_the_tail_and_drops_the_head(sample):
    assert truncate_file(sample, 1000, cut=TruncateSide.HEAD) == sample
    assert sample.read_bytes() == _DATA[-1000:]


def test_the_default_keeps_the_newest_bytes(sample):
    # HEAD by default: the case this exists for is a log, where the end
    # is the part worth keeping. Pinned so that changing it has to be
    # deliberate.
    truncate_file(sample, 1000)

    assert sample.read_bytes() == _DATA[-1000:]


def test_the_path_that_comes_back_is_the_resolved_one(sample):
    # resolve_path is what the function works with, so that is what it
    # hands back -- a caller can stat or reopen it without rebuilding it.
    got = truncate_file(sample, 100)

    assert got.is_absolute()
    assert got.stat().st_size == 100


def test_size_is_what_stays_not_what_goes(sample):
    # The argument names the size the file is left at, on either end --
    # not an amount to remove from it.
    truncate_file(sample, 1500, cut=TruncateSide.HEAD)
    assert sample.stat().st_size == 1500

    sample.write_bytes(_DATA)
    truncate_file(sample, 1500, cut=TruncateSide.TAIL)
    assert sample.stat().st_size == 1500


def test_a_file_already_small_enough_is_left_alone(sample):
    assert truncate_file(sample, len(_DATA)) == sample
    assert truncate_file(sample, len(_DATA) + 1) == sample
    # with spill on there is a list to answer with, and nothing in it
    assert truncate_file(sample, len(_DATA), spill=True) == []
    assert sample.read_bytes() == _DATA


@pytest.mark.parametrize("cut", ["tail", "head"])
def test_the_parts_and_the_file_put_the_original_back_together(sample, cut):
    # The whole promise of spilling: nothing is lost, and reassembly is a
    # concatenation in numbered order and nothing cleverer.
    parts = truncate_file(sample, 3000, cut=cut, spill=True)

    assert [p.name for p in parts] == ["app.log.1", "app.log.2", "app.log.3"]
    assert [p.stat().st_size for p in parts] == [3000, 3000, 1240]

    joined = b"".join(p.read_bytes() for p in parts)

    if cut == "tail":
        assert sample.read_bytes() + joined == _DATA
    else:
        assert joined + sample.read_bytes() == _DATA


def test_the_parts_go_beside_the_file_by_default(sample, tmp_path):
    parts = truncate_file(sample, 4096, spill=True)

    assert {p.parent for p in parts} == {tmp_path}


def test_the_parts_go_where_they_are_told_and_the_directory_is_made(sample, tmp_path):
    into = tmp_path / "chunks" / "deep"

    parts = truncate_file(sample, 4096, spill=into)

    assert into.is_dir()
    assert {p.parent for p in parts} == {into}
    assert b"".join(p.read_bytes() for p in parts) == _DATA[4096:]


def test_a_second_truncation_numbers_on_from_the_first(sample):
    first = truncate_file(sample, 3000, cut=TruncateSide.TAIL, spill=True)
    sample.write_bytes(_DATA)
    second = truncate_file(sample, 3000, cut=TruncateSide.TAIL, spill=True)

    assert [p.name for p in first] == ["app.log.1", "app.log.2", "app.log.3"]
    assert [p.name for p in second] == ["app.log.4", "app.log.5", "app.log.6"]
    # and the first set still holds what it held
    assert b"".join(p.read_bytes() for p in first) == _DATA[3000:]


def test_a_neighbour_that_is_not_a_part_does_not_move_the_numbering(sample, tmp_path):
    # Only an all-digit suffix is a part. A backup sitting beside the file
    # must neither push the count up nor be counted as one and read back.
    (tmp_path / "app.log.bak").write_bytes(b"unrelated")
    (tmp_path / "app.log.2x").write_bytes(b"unrelated")

    parts = truncate_file(sample, 4096, spill=True)

    assert [p.name for p in parts] == ["app.log.1", "app.log.2"]
    assert (tmp_path / "app.log.bak").read_bytes() == b"unrelated"


@pytest.mark.parametrize("length", [1, 5, 9, 10, 99, 100, 101, 4096, 100_000])
def test_size_zero_cuts_the_spill_into_ten_parts_at_most(tmp_path, length):
    # size=0 keeps nothing, so it names no part size and one is worked out
    # instead: a tenth of the spill, rounded up. Two properties, and both
    # have been wrong at some point --
    #
    #   never 0, which writes no part at all and then empties the file, so
    #   the bytes end up in neither place. A floor division does that for
    #   anything under ten bytes.
    #
    #   never more than ten, which is the whole reason it is a share of
    #   the file rather than a fixed length: a 4 GB file in 1 MiB parts is
    #   four thousand of them.
    path = tmp_path / "whole.bin"
    data = bytes((i * 7 + 3) % 256 for i in range(length))
    path.write_bytes(data)

    parts = truncate_file(path, 0, spill=True)

    assert 1 <= len(parts) <= 10, f"{length} bytes came back as {len(parts)} parts"
    assert all(p.stat().st_size > 0 for p in parts)
    assert b"".join(p.read_bytes() for p in parts) == data
    assert path.stat().st_size == 0


def test_size_zero_spills_the_whole_file(sample):
    # Nothing is kept, so there is no part size to read off the argument
    # and the copy buffer is the only number left.
    parts = truncate_file(sample, 0, spill=True)

    assert sample.read_bytes() == b""
    assert b"".join(p.read_bytes() for p in parts) == _DATA


def test_spilling_off_loses_the_bytes_and_answers_with_the_file(sample, tmp_path):
    # Nothing was split, so there is one file in play and its own path is
    # the answer -- an empty list said nothing about what happened.
    assert truncate_file(sample, 3000) == sample
    assert sorted(p.name for p in tmp_path.iterdir()) == ["app.log"]


def test_spilling_answers_with_the_parts_and_not_with_the_file(sample):
    got = truncate_file(sample, 3000, spill=True)

    assert isinstance(got, list)
    assert sample not in got
    assert [p.name for p in got] == ["app.log.1", "app.log.2", "app.log.3"]


def test_the_raw_string_picks_the_same_end_as_the_enum(tmp_path):
    for spelling in ("head", TruncateSide.HEAD):
        path = tmp_path / f"x{spelling!s}.bin"
        path.write_bytes(_DATA)
        truncate_file(path, 500, cut=spelling)
        assert path.read_bytes() == _DATA[-500:]


@pytest.mark.parametrize("bad", [-1, 3.5, True, "1000", None])
def test_a_size_that_is_not_a_count_of_bytes_is_refused(sample, bad):
    with pytest.raises(ValidationError, match="whole number of bytes"):
        truncate_file(sample, bad)

    assert sample.read_bytes() == _DATA


def test_a_directory_is_not_a_file_to_truncate(tmp_path):
    with pytest.raises(ValidationError, match="is not a file"):
        truncate_file(tmp_path, 10)


def test_a_missing_file_is_reported_as_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        truncate_file(tmp_path / "nope.log", 10)


def test_nothing_temporary_is_left_behind(sample, tmp_path):
    truncate_file(sample, 3000, cut="head", spill=True)

    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_a_head_cut_keeps_the_file_mode(sample):
    sample.chmod(0o640)

    truncate_file(sample, 3000, cut="head")

    assert sample.stat().st_mode & 0o777 == 0o640


# ---------------------------------------------------------------------
# ensure_dir
# ---------------------------------------------------------------------

def test_ensure_dir_makes_the_directory_and_hands_the_path_back(tmp_path):
    target = tmp_path / "logs"

    got = ensure_dir(target)

    assert got == target
    assert got.is_dir()


def test_ensure_dir_makes_every_missing_level(tmp_path):
    # parents defaults to True where mkdir's own default is False.
    got = ensure_dir(tmp_path / "a" / "b" / "c")

    assert got.is_dir()
    assert (tmp_path / "a" / "b").is_dir()


def test_ensure_dir_for_a_file_makes_the_directory_above_it(tmp_path):
    target = tmp_path / "out" / "2024" / "log.txt"

    got = ensure_dir(target, for_file=True)

    assert got == target
    assert got.parent.is_dir()
    # the file itself is not created -- it is the caller's to write
    assert not got.exists()


def test_a_path_from_ensure_dir_is_writable_straight_away(tmp_path):
    # The reason it returns the argument rather than the directory: it
    # composes with the writers, in one expression and no temporary.
    path = write_file(
        ensure_dir(tmp_path / "deep" / "nest" / "note.txt", for_file=True),
        "hello", fsync=False,
    )

    assert (tmp_path / "deep" / "nest" / "note.txt").read_text(encoding="utf-8") == "hello"


def test_ensure_dir_is_content_with_a_directory_that_is_already_there(tmp_path):
    target = ensure_dir(tmp_path / "twice")

    assert ensure_dir(target) == target


def test_ensure_dir_passes_exist_ok_through(tmp_path):
    target = ensure_dir(tmp_path / "once")

    with pytest.raises(FileExistsError):
        ensure_dir(target, exist_ok=False)


def test_ensure_dir_passes_parents_through(tmp_path):
    with pytest.raises(FileNotFoundError):
        ensure_dir(tmp_path / "no" / "such" / "parent", parents=False)


def test_a_file_standing_where_a_directory_was_asked_for_is_not_forgiven(tmp_path):
    # exist_ok forgives a directory and nothing else, which is right: the
    # caller asked for a directory there and there is not one.
    occupied = tmp_path / "occupied"
    occupied.write_text("i am a file", encoding="utf-8")

    with pytest.raises(FileExistsError):
        ensure_dir(occupied)


def test_ensure_dir_takes_a_string_and_returns_a_path(tmp_path):
    got = ensure_dir(str(tmp_path / "from_str"))

    assert isinstance(got, Path)
    assert got.is_dir()


def test_ensure_dir_does_not_resolve_what_it_is_given(tmp_path, monkeypatch):
    # Relative stays relative: the caller gets back what it passed in, and
    # reaches for resolve_path when it wants an absolute one.
    monkeypatch.chdir(tmp_path)

    got = ensure_dir("relative/here")

    assert got == Path("relative/here")
    assert not got.is_absolute()
    assert (tmp_path / "relative" / "here").is_dir()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_ensure_dir_passes_mode_through(tmp_path):
    got = ensure_dir(tmp_path / "narrow", mode=0o700)

    assert got.stat().st_mode & 0o777 == 0o700 & ~_umask()


def _umask():
    old = os.umask(0)
    os.umask(old)
    return old


def test_mkdir_options_lists_exactly_what_mkdir_takes():
    # The point of forwarding **kwargs is that this stays the only place
    # the keywords are written down. Read off Path.mkdir itself, so a
    # keyword the stdlib adds or drops fails here rather than silently
    # being unavailable through ensure_dir.
    taken = {
        name for name, param in inspect.signature(Path.mkdir).parameters.items()
        if name != "self"
        and param.kind in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY)
    }

    assert set(_MkdirOptions.__annotations__) == taken


def test_every_mkdir_option_is_optional():
    # total=False: a caller passes the one it cares about and ensure_dir
    # fills the rest, so none of them may be required.
    assert _MkdirOptions.__optional_keys__ == frozenset(_MkdirOptions.__annotations__)
    assert _MkdirOptions.__required_keys__ == frozenset()


def test_a_keyword_mkdir_does_not_take_is_refused_by_name(tmp_path):
    # Unpack is a static check and does nothing at runtime, so the runtime
    # answer comes from mkdir -- which still names the offending keyword.
    with pytest.raises(TypeError, match="parent"):
        ensure_dir(tmp_path / "typo", parent=True)


# ---------------------------------------------------------------------
# remove_files / remove_folders / remove_paths
# ---------------------------------------------------------------------

def _dir_link(link, target):
    """Point `link` at directory `target`, however this platform can.

    A symlink where the account may make one, and a Windows junction
    otherwise -- an ordinary Windows account holds no
    SeCreateSymbolicLinkPrivilege, and a junction needs none. The two are
    the same hazard for this code and differ in exactly the way that
    matters: a junction reports neither islink() nor is_symlink().
    """

    try:
        link.symlink_to(target, target_is_directory=True)
        return "symlink"
    except (OSError, NotImplementedError):
        if sys.platform != "win32":
            return None

    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, check=False,
    )

    return "junction" if made.returncode == 0 else None


@pytest.fixture
def linked(tmp_path):
    """A link to a directory that holds something worth not losing."""

    target = tmp_path / "TARGET"
    target.mkdir()
    (target / "precious.txt").write_text("precious", encoding="utf-8")

    link = tmp_path / "link"
    kind = _dir_link(link, target)

    if kind is None:
        pytest.skip("cannot link to a directory here")

    return link, target


@pytest.mark.parametrize("remove", [remove_file, remove_folder, remove_path])
def test_a_link_to_a_directory_is_removed_and_its_target_is_not(linked, remove):
    # The link is one entry and is removed as one. Following it would take
    # out a tree nobody named -- and a junction is the case that catches a
    # check written as is_dir(), since it reports neither islink() nor
    # is_symlink() while answering is_dir() True.
    link, target = linked

    remove(link)

    assert not os.path.lexists(link)
    assert (target / "precious.txt").read_text(encoding="utf-8") == "precious"


@pytest.mark.parametrize("remove", [remove_file, remove_folder, remove_path])
def test_a_path_that_was_never_there_is_not_a_failure(tmp_path, caplog, remove):
    # Making sure a path is gone, and it is gone. Calling twice must not
    # be an error either.
    with caplog.at_level("WARNING"):
        remove(tmp_path / "ghost")

    assert caplog.text == ""


def test_removing_a_tree_takes_everything_under_it(tmp_path):
    deep = tmp_path / "tree" / "a" / "b"
    deep.mkdir(parents=True)
    (deep / "leaf.txt").write_text("leaf", encoding="utf-8")

    remove_path(tmp_path / "tree")

    assert not (tmp_path / "tree").exists()


def test_remove_files_returns_what_it_actually_removed(tmp_path):
    one = tmp_path / "one.txt"
    two = tmp_path / "two.txt"
    one.write_text("1", encoding="utf-8")
    two.write_text("2", encoding="utf-8")

    assert remove_file(one, two) == [one, two]
    assert not one.exists() and not two.exists()


def test_a_missing_path_is_success_and_is_not_in_the_result(tmp_path):
    # These are for making sure a path is gone, and one that was never
    # there is gone. Calling twice is not an error.
    gone = tmp_path / "ghost"
    real = tmp_path / "real.txt"
    real.write_text("x", encoding="utf-8")

    assert remove_file(gone, real) == [real]
    assert remove_file(gone, real) == []


def test_the_same_path_twice_is_one_unlink(tmp_path):
    # Flattened to Path first and de-duplicated after, so the two spellings
    # of one file are one entry -- they compare unequal as they arrive.
    target = tmp_path / "a.txt"
    target.write_text("x", encoding="utf-8")

    assert remove_file(str(target), target, [target]) == [target]


def test_a_directory_handed_to_remove_file_raises_by_default(tmp_path):
    # os.unlink refuses a real directory, and refusing is right: remove_file
    # removes one entry, and a directory is however much someone put in it.
    target = tmp_path / "a_dir"
    target.mkdir()

    with pytest.raises(OSError):
        remove_file(target)

    assert target.is_dir()


def test_return_exc_collects_the_refusal_and_carries_on(tmp_path):
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


def test_remove_folders_returns_what_it_actually_removed(tmp_path):
    d1 = tmp_path / "d1"
    d2 = tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    (d1 / "inside.txt").write_text("x", encoding="utf-8")

    assert remove_folder(d1, d2) == [d1, d2]
    assert not d1.exists() and not d2.exists()


def test_remove_folders_treats_a_missing_directory_as_success(tmp_path):
    real = tmp_path / "real"
    real.mkdir()

    assert remove_folder(tmp_path / "ghost", real) == [real]
    assert remove_folder(tmp_path / "ghost") == []


def test_remove_folders_refuses_a_file_by_default(tmp_path):
    # Only a real directory is something rmtree can walk -- a file handed
    # here is refused rather than resolved into one.
    target = tmp_path / "a_file.txt"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(OSError):
        remove_folder(target)

    assert target.is_file()


def test_remove_folders_return_exc_collects_and_carries_on(tmp_path):
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


def test_remove_folders_log_exc_names_the_directory(tmp_path, caplog):
    target = tmp_path / "a_file.txt"
    target.write_text("x", encoding="utf-8")

    with caplog.at_level("WARNING"):
        remove_folder(target, return_exc=True, log_exc=True)

    record = caplog.records[0]

    assert record.levelname == "ERROR"
    assert record.exc_info is not None
    assert record.getMessage() == f"remove_folders: could not remove {target}"


def test_remove_folders_takes_the_junction_and_not_the_tree(tmp_path):
    # rmtree refuses a reparse point outright, since the kernel counts it
    # as a directory -- the onerror hook is what turns that refusal into an
    # unlink of the link itself, never of what it points at.
    target = tmp_path / "real"
    target.mkdir()
    (target / "inside.txt").write_text("kept", encoding="utf-8")

    link = tmp_path / "link"

    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            pytest.skip("cannot create a link here")

        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                              capture_output=True)

        if made.returncode != 0:
            pytest.skip("cannot create a junction here")

    remove_folder(link)

    assert not os.path.lexists(link)
    assert (target / "inside.txt").read_text(encoding="utf-8") == "kept"


def test_remove_paths_dispatches_by_kind(tmp_path):
    a_dir = tmp_path / "a_dir"
    a_dir.mkdir()
    (a_dir / "inside.txt").write_text("x", encoding="utf-8")
    a_file = tmp_path / "a_file.txt"
    a_file.write_text("x", encoding="utf-8")

    assert remove_path(a_dir, a_file) == [a_dir, a_file]
    assert not a_dir.exists() and not a_file.exists()


def test_remove_paths_forwards_return_exc_and_log_exc(tmp_path, caplog):
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


def test_every_exception_carries_its_own_path(tmp_path):
    # A list of exceptions is read somewhere else entirely, so each one has
    # to say what it is about. `filename` is the slot OSError.__str__
    # reads, which puts the path in the message rather than only on the
    # object.
    stubborn = tmp_path / "a_dir"
    stubborn.mkdir()
    other = tmp_path / "b_dir"
    other.mkdir()

    a, b = remove_file(stubborn, other, return_exc=True)

    assert a.filename == str(stubborn)
    assert b.filename == str(other)

    # OSError.__str__ writes the filename with repr(), which doubles every
    # separator on Windows -- so the message is searched for what it really
    # holds rather than for the path as the caller spelled it.
    assert repr(str(stubborn)) in str(a)


def test_the_path_on_the_exception_is_the_normalised_one(tmp_path):
    # os.unlink fills `filename` with the path exactly as it was handed
    # over -- a trailing slash and all -- and this rewrites it from the
    # Path, so a hundred exceptions read in one spelling.
    stubborn = tmp_path / "a_dir"
    stubborn.mkdir()

    odd = str(stubborn) + "/"
    exc = remove_file(odd, return_exc=True)[0]

    assert exc.filename == str(stubborn)
    assert not exc.filename.endswith("/")


def test_log_exc_names_the_path_and_brings_the_traceback(tmp_path, caplog):
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


def test_log_exc_says_nothing_for_an_exception_that_is_raised(tmp_path, caplog):
    # Same rule as safe_call: one that propagates was never handled here,
    # so logging it as well would report one failure twice under two
    # different owners.
    target = tmp_path / "a_dir"
    target.mkdir()

    with caplog.at_level("WARNING"):
        with pytest.raises(OSError):
            remove_file(target, log_exc=True)

    assert caplog.text == ""


def test_a_raised_exception_is_annotated_too(tmp_path):
    # The path goes on before the raise, not after the decision to collect,
    # so a caller that catches one is handed the same exception a caller
    # that collects it would have got.
    target = tmp_path / "a_dir"
    target.mkdir()

    with pytest.raises(OSError) as caught:
        remove_file(str(target) + "/")

    assert caught.value.filename == str(target)


def test_atomic_write_does_not_let_its_cleanup_mask_the_blocks_error(tmp_path, monkeypatch):
    # The removal runs in a finally. An exception from there would replace
    # whatever the caller's block was already raising, and a leftover .tmp
    # is not worth losing that.
    monkeypatch.setattr(
        os, "unlink",
        lambda *a, **kw: (_ for _ in ()).throw(PermissionError(13, "held")),
    )

    with pytest.raises(ValueError, match="the block's own"):
        with atomic_write(tmp_path / "out.txt") as f:
            f.write("x")
            raise ValueError("the block's own error")


def test_the_removers_take_any_nesting_of_paths(tmp_path):
    made = []

    for name in ("a.txt", "b.txt", "c.txt"):
        path = tmp_path / name
        path.write_text("x", encoding="utf-8")
        made.append(path)

    remove_path(made[0], [made[1], (made[2],)])

    assert not any(p.exists() for p in made)


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
        assert bool(internals._is_link(path)) == _own_islink(path), path


def test_a_missing_path_is_not_a_link(tmp_path):
    # Not an error either: the removers ask this about paths that may well
    # have gone, and every branch of _is_link swallows the OSError itself.
    assert not internals._is_link(tmp_path / "never")
    assert not internals._is_dir(tmp_path / "never")


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
    assert internals._is_link(link)
    assert internals._is_dir(link) is False
    assert internals._is_dir(target) is True

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

    assert bool(internals._is_link("anything")) is link
    assert internals._is_dir("anything") is plain_dir


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
    assert internals._is_link(__file__) == _own_islink(__file__)


def test_is_dir_is_the_inverse_of_is_link_for_a_directory(tmp_path):
    a_dir = tmp_path / "d"
    a_dir.mkdir()
    a_file = tmp_path / "f.txt"
    a_file.write_text("x", encoding="utf-8")

    assert internals._is_dir(a_dir) is True
    assert internals._is_dir(a_file) is False
    assert internals._is_dir(tmp_path / "ghost") is False
