from __future__ import annotations as _annotations

import collections
import json
import os
import pickle
import threading
from datetime import datetime
from pathlib import Path

import pytest

from pytrove.enums import PickleSafety
from pytrove.files_tools import (
    ensure_path,
    load_json,
    load_ref_json,
    read_file,
    read_json,
    read_pickle,
    resolve_path,
    save_json,
    write_json,
    write_pickle,
)


class Custom:
    """A class pickled by tests to exercise the safety levels."""

    def __init__(self, value: int) -> None:
        """Store `value`."""
        self.value = value


def test_ensure_path_returns_a_path_as_is() -> None:
    path = Path("x")
    assert ensure_path(path) is path
    assert ensure_path("x") == Path("x")


def test_ensure_path_decodes_bytes_paths() -> None:
    assert ensure_path(b"x") == Path("x")
    assert ensure_path(os.fsencode(Path("a") / "b")) == Path("a") / "b"


def test_resolve_path_is_absolute_and_strict_on_request(tmp_path: Path) -> None:
    assert resolve_path("relative").is_absolute()

    with pytest.raises(FileNotFoundError):
        resolve_path(tmp_path / "missing", strict=True)


def test_read_file_reads_text_or_bytes_and_holds_the_lock(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_bytes("é".encode())
    lock = threading.Lock()
    assert read_file(target, lock=lock) == "é"
    assert read_file(target, binary=True) == "é".encode()
    assert not lock.locked()

    with pytest.raises(FileNotFoundError):
        read_file(tmp_path / "missing")


def test_json_round_trip_and_aliases(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    write_json(target, {"a": [1, "é"]})
    assert read_json(target) == {"a": [1, "é"]}
    assert "é" in target.read_text(encoding="utf-8")
    assert load_json is read_json
    assert save_json is write_json


def test_read_json_default_for_a_missing_file(tmp_path: Path) -> None:
    assert read_json(tmp_path / "missing.json") == {}
    assert read_json(tmp_path / "missing.json", default=None) is None


def test_json_keywords_fall_back_to_the_standard_codec(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    write_json(target, {"b": 1, "a": 2}, indent=4, sort_keys=True)
    assert target.read_text(encoding="utf-8") == json.dumps({"a": 2, "b": 1}, indent=4)
    assert read_json(target, parse_int=str) == {"a": "2", "b": "1"}


def test_write_json_hands_datetimes_to_default_like_json(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        write_json(tmp_path / "d.json", {"t": datetime(2024, 1, 1)})

    write_json(tmp_path / "d.json", {"t": datetime(2024, 1, 1)}, default=str)
    assert read_json(tmp_path / "d.json") == {"t": "2024-01-01 00:00:00"}


def test_pickle_round_trip_of_safe_types(tmp_path: Path) -> None:
    target = tmp_path / "data.pkl"
    data = {"a": [1, 2.5, "x"], "b": collections.OrderedDict(c=1), "d": Path("p")}
    write_pickle(target, data)
    assert read_pickle(target) == data


def test_read_pickle_default_for_a_missing_file(tmp_path: Path) -> None:
    assert read_pickle(tmp_path / "missing.pkl") == {}
    assert read_pickle(tmp_path / "missing.pkl", default=0) == 0


def test_strict_refuses_an_unknown_class_unless_allowed(tmp_path: Path) -> None:
    target = tmp_path / "custom.pkl"
    write_pickle(target, Custom(3))

    with pytest.raises(pickle.UnpicklingError, match="refusing to load"):
        read_pickle(target)

    assert read_pickle(target, allow_classes=[Custom]).value == 3
    assert read_pickle(target, safe=PickleSafety.MODULES, allow_modules=__name__).value == 3
    assert read_pickle(target, safe=PickleSafety.BLOCKLIST).value == 3
    assert read_pickle(target, safe=False).value == 3

    with pytest.raises(pickle.UnpicklingError):
        read_pickle(target, safe=True)


def test_blocklist_refuses_an_execution_vector(tmp_path: Path) -> None:
    target = tmp_path / "evil.pkl"
    target.write_bytes(pickle.dumps(eval, protocol=2))

    with pytest.raises(pickle.UnpicklingError):
        read_pickle(target, safe=PickleSafety.BLOCKLIST)


def test_load_ref_json_resolves_relative_references(tmp_path: Path) -> None:
    (tmp_path / "part.json").write_text('{"n": 1}', encoding="utf-8")
    (tmp_path / "main.json").write_text('{"x": {"$ref": "part.json"}}', encoding="utf-8")
    assert load_ref_json(tmp_path / "main.json") == {"x": {"n": 1}}
    assert load_ref_json(tmp_path / "missing.json") == {}
    assert load_ref_json(tmp_path / "missing.json", default=None) is None
