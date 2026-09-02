import glob
import json
import os

import pytest

from pytrove import load_json, save_json, truncate_file
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
    assert truncate_file(sample, 1000) == []
    assert sample.read_bytes() == _DATA[:1000]


def test_truncate_keeps_the_tail_and_drops_the_head(sample):
    assert truncate_file(sample, 1000, cut=TruncateSide.HEAD) == []
    assert sample.read_bytes() == _DATA[-1000:]


def test_a_file_already_small_enough_is_left_alone(sample):
    assert truncate_file(sample, len(_DATA)) == []
    assert truncate_file(sample, len(_DATA) + 1) == []
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
    first = truncate_file(sample, 3000, spill=True)
    sample.write_bytes(_DATA)
    second = truncate_file(sample, 3000, spill=True)

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


def test_size_zero_spills_the_whole_file(sample):
    # Nothing is kept, so there is no part size to read off the argument
    # and the copy buffer is the only number left.
    parts = truncate_file(sample, 0, spill=True)

    assert sample.read_bytes() == b""
    assert b"".join(p.read_bytes() for p in parts) == _DATA


def test_spilling_off_loses_the_bytes_and_says_so_by_returning_nothing(sample, tmp_path):
    assert truncate_file(sample, 3000) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["app.log"]


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
