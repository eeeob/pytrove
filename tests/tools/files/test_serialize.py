"""`files_tools.serialize`: JSON and pickle files, and `load_ref_json`."""

from __future__ import annotations as _annotations

import collections
import collections.abc
import enum
import glob
import json
import pickle
import threading
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, call

import pytest

from pytrove.enums import PickleSafety
import pytrove
from pytrove.files_tools import (
    load_ref_json,
    read_json,
    read_pickle,
    write_json,
    write_pickle,
)
from pytrove.files_tools import serialize as serialize_module

#: What a lock that was taken and given back records.
_HELD = [call.acquire(), call.release()]


class _Colour(enum.Enum):
    RED = "red"


class Custom:
    """A class pickled by tests to exercise the safety levels."""

    def __init__(self, value: int) -> None:
        """Store `value`."""
        self.value = value


# The failure is triggered by data `json` cannot encode, rather than by monkeypatching it.
class _Unserialisable:
    pass


# --- read_json / write_json ------------------------------------------------


def test_json_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    write_json(target, {"a": [1, "é"]})
    assert read_json(target) == {"a": [1, "é"]}
    assert "é" in target.read_text(encoding="utf-8")


@pytest.mark.parametrize("old", ["load_json", "save_json"])
def test_the_load_and_save_names_are_gone(old: str) -> None:
    assert not hasattr(pytrove, old)
    assert not hasattr(serialize_module, old)


def test_write_json_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    write_json(path, {"a": 1})
    assert glob.glob(str(path) + "*.tmp") == []


def test_read_json_default_for_a_missing_file(tmp_path: Path) -> None:
    assert read_json(tmp_path / "missing.json") == {}
    assert read_json(tmp_path / "missing.json", default=None) is None
    assert read_json(tmp_path / "missing.json", default={"fallback": True}) == {"fallback": True}


def test_read_json_corrupted_or_empty_file_raises_decode_error(tmp_path: Path) -> None:
    # By design, only a missing file falls back to `default` -- a corrupted
    # file raises loudly instead of silently returning `default` and masking
    # the corruption.
    corrupted = tmp_path / "corrupted.json"
    corrupted.write_text("{not valid json!!!", encoding="utf-8")
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")

    for path in (corrupted, empty):
        with pytest.raises(ValueError):  # `json.JSONDecodeError` is one
            read_json(path, default={"fallback": True})


def test_json_keywords_reach_the_codec(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    write_json(target, {"b": 1, "a": 2}, indent=4, sort_keys=True)
    assert target.read_text(encoding="utf-8") == json.dumps({"a": 2, "b": 1}, indent=4)
    assert read_json(target, parse_int=str) == {"a": "2", "b": "1"}


def test_write_json_escapes_to_ascii_only_on_request(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    write_json(target, {"k": "é"}, ensure_ascii=True)
    assert target.read_text(encoding="utf-8") == '{"k": "\\u00e9"}'


def test_write_json_hands_datetimes_to_default_like_json(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        write_json(tmp_path / "d.json", {"t": datetime(2024, 1, 1)})

    write_json(tmp_path / "d.json", {"t": datetime(2024, 1, 1)}, default=str)
    assert read_json(tmp_path / "d.json") == {"t": "2024-01-01 00:00:00"}


def test_write_json_failure_leaves_no_temp_file_and_the_old_file_intact(tmp_path: Path) -> None:
    path = tmp_path / "data.json"

    with pytest.raises(TypeError):
        write_json(path, {"a": _Unserialisable()})

    assert glob.glob(str(path) + "*.tmp") == []
    assert not path.exists()

    write_json(path, {"a": 1})

    with pytest.raises(TypeError):
        write_json(path, {"a": _Unserialisable()})

    # The atomic replace never happened, so the original content must survive.
    assert read_json(path) == {"a": 1}


def test_json_io_holds_the_lock_and_skips_fsync_on_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "data.json"
    lock = Mock()
    synced: list[int] = []
    monkeypatch.setattr("os.fsync", synced.append)

    write_json(target, {"a": 1}, lock=lock, fsync=False)
    assert lock.mock_calls == _HELD
    assert synced == []

    real_lock = threading.Lock()
    assert read_json(target, lock=real_lock) == {"a": 1}
    assert not real_lock.locked()


# --- JSON as plain `json` reads and writes it -------------------------------


@pytest.mark.parametrize(
    "data",
    [
        2**70,
        -(2**64),
        float("nan"),
        float("inf"),
        "é",
        {1: "x", None: "y"},
        {"big": [2**70, 1.5], "s": "ü"},
    ],
    ids=repr,
)
def test_json_round_trips_exactly_as_plain_json_does(tmp_path: Path, data: object) -> None:
    # Big ints must stay ints, NaN must stay NaN.
    target = tmp_path / "data.json"
    write_json(target, data)

    assert target.read_bytes() == json.dumps(data, ensure_ascii=False).encode()
    assert repr(read_json(target)) == repr(json.loads(json.dumps(data)))


@pytest.mark.parametrize("value", [_Colour.RED, uuid.UUID(int=1)], ids=repr)
def test_json_refuses_what_plain_json_refuses(tmp_path: Path, value: object) -> None:
    # `json` hands these to `default`, which raises by default.
    with pytest.raises(TypeError):
        write_json(tmp_path / "data.json", {"v": value})

    write_json(tmp_path / "data.json", {"v": value}, default=lambda v: "custom")
    assert read_json(tmp_path / "data.json") == {"v": "custom"}


@pytest.mark.parametrize("kw", [{}, {"indent": 2}, {"indent": 2, "sort_keys": True}], ids=repr)
def test_write_json_bytes_do_not_depend_on_the_platform(
    tmp_path: Path, kw: dict[str, object]
) -> None:
    # Written as bytes, so Windows' text mode cannot turn the newlines into CRLF.
    target = tmp_path / "data.json"
    write_json(target, {"b": 1, "a": [1, 2]}, **kw)

    assert target.read_bytes() == json.dumps({"b": 1, "a": [1, 2]}, **kw).encode()
    assert b"\r" not in target.read_bytes()


@pytest.mark.parametrize(
    ("content", "expected"),
    [(b"\xef\xbb\xbf{}", "{}"), (b"[NaN, -Infinity]", "[nan, -inf]"), (b"1e400", "inf")],
)
def test_read_json_takes_what_plain_json_takes(
    tmp_path: Path, content: bytes, expected: str
) -> None:
    target = tmp_path / "data.json"
    target.write_bytes(content)

    assert repr(read_json(target)) == expected


def test_write_json_takes_any_object_default_can_handle(tmp_path: Path) -> None:
    # Typed `object`: a `dict[str, list[int]]` or a tuple is not a `JsonValue`, being invariant.
    payload: dict[str, list[int]] = {"a": [1]}
    write_json(tmp_path / "a.json", payload)
    write_json(tmp_path / "t.json", (1, 2))

    assert read_json(tmp_path / "a.json") == {"a": [1]}
    assert read_json(tmp_path / "t.json") == [1, 2]


# --- read_pickle / write_pickle --------------------------------------------


def test_pickle_round_trip_of_safe_types(tmp_path: Path) -> None:
    target = tmp_path / "data.pkl"
    data = {"a": [1, 2.5, "x"], "b": collections.OrderedDict(c=1), "d": Path("p")}
    write_pickle(target, data)
    assert read_pickle(target) == data


def test_write_pickle_uses_the_highest_protocol_unless_told(tmp_path: Path) -> None:
    target = tmp_path / "data.pkl"
    write_pickle(target, [1])
    assert target.read_bytes()[1] == pickle.HIGHEST_PROTOCOL

    write_pickle(target, [1], protocol=2, fsync=False)
    assert target.read_bytes()[1] == 2
    assert read_pickle(target) == [1]


def test_pickle_io_holds_the_lock(tmp_path: Path) -> None:
    target = tmp_path / "data.pkl"
    writing, reading = Mock(), Mock()

    write_pickle(target, 1, lock=writing)
    assert read_pickle(target, lock=reading) == 1
    assert writing.mock_calls == reading.mock_calls == _HELD


def test_read_pickle_default_for_a_missing_file(tmp_path: Path) -> None:
    assert read_pickle(tmp_path / "missing.pkl") == {}
    assert read_pickle(tmp_path / "missing.pkl", default=0) == 0
    assert read_pickle(tmp_path / "missing.pkl", default=None) is None


def test_strict_refuses_an_unknown_class_unless_allowed(tmp_path: Path) -> None:
    target = tmp_path / "custom.pkl"
    write_pickle(target, Custom(3))

    with pytest.raises(pickle.UnpicklingError, match="refusing to load"):
        read_pickle(target)

    assert read_pickle(target, allow_classes=[Custom]).value == 3
    assert read_pickle(target, allow_classes=[[Custom], (int,)]).value == 3
    assert read_pickle(target, safe=PickleSafety.MODULES, allow_modules=__name__).value == 3
    assert read_pickle(target, safe=PickleSafety.MODULES, allow_modules=[[__name__]]).value == 3
    assert read_pickle(target, safe=PickleSafety.BLOCKLIST).value == 3
    assert read_pickle(target, safe=PickleSafety.NONE).value == 3
    assert read_pickle(target, safe=False).value == 3

    with pytest.raises(pickle.UnpicklingError):
        read_pickle(target, safe=True)

    with pytest.raises(pickle.UnpicklingError):
        read_pickle(target, safe=PickleSafety.MODULES, allow_modules="some.other")


def test_read_pickle_forwards_unpickler_keywords(tmp_path: Path) -> None:
    target = tmp_path / "data.pkl"
    buffers: list[pickle.PickleBuffer] = []
    write_pickle(
        target,
        {"k": pickle.PickleBuffer(bytearray(b"v"))},
        protocol=5,
        buffer_callback=buffers.append,
    )
    raw = [b.raw() for b in buffers]
    assert raw  # out of band, so the file alone is not enough

    assert read_pickle(target, buffers=raw) == {"k": bytearray(b"v")}
    assert read_pickle(target, safe=False, buffers=raw) == {"k": bytearray(b"v")}

    with pytest.raises(pickle.UnpicklingError):  # the out-of-band buffer is required
        read_pickle(target, buffers=[])


def test_blocklist_refuses_an_execution_vector(tmp_path: Path) -> None:
    target = tmp_path / "evil.pkl"
    target.write_bytes(pickle.dumps(eval, protocol=2))

    with pytest.raises(pickle.UnpicklingError):
        read_pickle(target, safe=PickleSafety.BLOCKLIST)

    assert read_pickle(target, safe=PickleSafety.NONE) is eval


@pytest.mark.parametrize("safe", [PickleSafety.BLOCKLIST, PickleSafety.MODULES])
def test_a_dotted_global_cannot_escape_through_an_allowed_module(
    tmp_path: Path, safe: PickleSafety
) -> None:
    # Protocol 4: `shutil` + `os.getcwd`, called with no arguments. `shutil.os` is
    # there on every supported version (`pathlib.os` is not, on 3.13).
    target = tmp_path / "evil.pkl"
    target.write_bytes(b"\x80\x04\x8c\x06shutil\x8c\x09os.getcwd\x93)R.")

    with pytest.raises(pickle.UnpicklingError, match="'shutil.os.getcwd'"):
        read_pickle(target, safe=safe, allow_modules="shutil")


@pytest.mark.parametrize("protocol", [0, 1, 2])
def test_strict_reads_old_protocols(tmp_path: Path, protocol: int) -> None:
    target = tmp_path / "old.pkl"
    write_pickle(target, {"b": b"ab", "c": Custom(3)}, protocol=protocol)

    loaded = read_pickle(target, allow_classes=[Custom])
    assert loaded["b"] == b"ab"
    assert loaded["c"].value == 3


def test_allow_modules_does_not_reach_submodules(tmp_path: Path) -> None:
    target = tmp_path / "abc.pkl"
    write_pickle(target, collections.abc.Sized)

    assert read_pickle(target, safe=PickleSafety.MODULES, allow_modules="collections.abc") is (
        collections.abc.Sized
    )

    with pytest.raises(pickle.UnpicklingError):
        read_pickle(target, safe=PickleSafety.MODULES, allow_modules="collections")


# --- load_ref_json ---------------------------------------------------------


def test_load_ref_json_resolves_relative_references(tmp_path: Path) -> None:
    pytest.importorskip("jsonref")
    (tmp_path / "part.json").write_text('{"n": 1}', encoding="utf-8")
    (tmp_path / "main.json").write_text(
        '{"x": {"$ref": "part.json"}, "y": {"$ref": "#/x"}}', encoding="utf-8"
    )

    resolved = load_ref_json(tmp_path / "main.json")

    assert resolved == {"x": {"n": 1}, "y": {"n": 1}}
    assert type(resolved["x"]) is dict  # `proxies=False`: real objects, not proxies
    assert load_ref_json(tmp_path / "missing.json") == {}
    assert load_ref_json(tmp_path / "missing.json", default=None) is None


def test_load_ref_json_takes_a_lock_and_jsonref_keywords(tmp_path: Path) -> None:
    jsonref = pytest.importorskip("jsonref")
    (tmp_path / "main.json").write_text('{"x": {"$ref": "#/y"}, "y": 1}', encoding="utf-8")
    lock = Mock()

    assert load_ref_json(tmp_path / "main.json", lock=lock) == {"x": 1, "y": 1}
    assert lock.mock_calls == _HELD

    proxied = load_ref_json(tmp_path / "main.json", proxies=True)
    assert isinstance(proxied["x"], jsonref.JsonRef)

    (tmp_path / "broken.json").write_text('{"x": {"$ref": "#/nope"}}', encoding="utf-8")

    with pytest.raises(jsonref.JsonRefError):  # `lazy_load=False`: a broken ref fails here
        load_ref_json(tmp_path / "broken.json")

    lazy = load_ref_json(tmp_path / "broken.json", proxies=True, lazy_load=True)
    with pytest.raises(jsonref.JsonRefError):  # `lazy_load=True`: only when the ref is used
        _ = lazy["x"]["anything"]


def test_load_ref_json_resolves_against_a_base_uri_given(tmp_path: Path) -> None:
    pytest.importorskip("jsonref")
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "part.json").write_text('{"n": 2}', encoding="utf-8")
    (tmp_path / "doc").mkdir()
    (tmp_path / "doc" / "main.json").write_text('{"x": {"$ref": "part.json"}}', encoding="utf-8")
    base = (tmp_path / "shared" / "index.json").as_uri()

    assert load_ref_json(tmp_path / "doc" / "main.json", base_uri=base) == {"x": {"n": 2}}
