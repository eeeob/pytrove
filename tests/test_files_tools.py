import glob
import inspect
import json
import os

import pytest

from pathlib import Path

from pytrove import ensure_dir, load_json, save_json, truncate_file, write_file
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
