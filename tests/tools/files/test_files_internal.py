"""`files_tools._internal`: JSON codecs, tree removal and spill parts."""

from __future__ import annotations as _annotations

import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from pytrove.enums import TruncateSide
from pytrove.files_tools import _internal
from pytrove.files_tools._internal import (
    _MkdirOptions,
    _json_dumps,
    _json_loads,
    _next_part,
    _on_exc_remove_folders,
    _remove,
    _rmtree,
    _spill_parts,
    _ORJSON_COMPAT,
    _ORJSON_DUMP_KEYS,
    _SPILL_PARTS,
    HAS_ORJSON,
)

needs_orjson = pytest.mark.skipif(not HAS_ORJSON, reason="needs the fastjson extra")


# --- constants and the options TypedDict -----------------------------------

def test_spill_parts_constant() -> None:
    assert _SPILL_PARTS == 10


def test_orjson_constants_follow_the_extra() -> None:
    assert _ORJSON_DUMP_KEYS == {"ensure_ascii", "indent", "sort_keys", "default"}

    if HAS_ORJSON:
        orjson = pytest.importorskip("orjson")
        assert _ORJSON_COMPAT == (
            orjson.OPT_PASSTHROUGH_DATETIME | orjson.OPT_PASSTHROUGH_DATACLASS | orjson.OPT_NON_STR_KEYS
        )
    else:
        assert _ORJSON_COMPAT == 0
        assert "orjson" not in sys.modules or sys.modules["orjson"] is None


def test_mkdir_options_lists_exactly_what_mkdir_takes() -> None:
    # The point of forwarding **kwargs is that this stays the only place
    # the keywords are written down. Read off Path.mkdir itself, so a
    # keyword the stdlib adds or drops fails here rather than silently
    # being unavailable through ensure_dir.
    taken = {
        name for name, param in inspect.signature(Path.mkdir).parameters.items()
        if name != "self" and param.kind in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY)
    }

    assert set(_MkdirOptions.__annotations__) == taken


def test_every_mkdir_option_is_optional() -> None:
    # total=False: a caller passes the one it cares about and ensure_dir
    # fills the rest, so none of them may be required.
    assert _MkdirOptions.__optional_keys__ == frozenset(_MkdirOptions.__annotations__)
    assert _MkdirOptions.__required_keys__ == frozenset()


# --- _next_part ------------------------------------------------------------

def test_next_part_counts_only_numeric_suffixes(tmp_path: Path) -> None:
    for name in ("app.log.1", "app.log.7", "app.log.bak", "other.log.9"):
        (tmp_path / name).write_text("", encoding="utf-8")

    assert _next_part(tmp_path, "app.log") == 8
    assert _next_part(tmp_path, "new.log") == 1
    assert _next_part(tmp_path / "missing", "app.log") == 1


# --- JSON codecs -----------------------------------------------------------

def test_json_codecs_round_trip_on_either_backend() -> None:
    encoded = _json_dumps({"a": 1}, {})
    assert _json_loads(encoded, {}) == {"a": 1}
    assert _json_loads(b'{"a": 1}', {}) == {"a": 1}
    assert _json_dumps({"a": 1}, {"indent": 4}) == '{\n    "a": 1\n}'
    assert _json_loads('{"a": 1.5}', {"parse_float": str}) == {"a": "1.5"}


@needs_orjson
def test_orjson_takes_the_fast_path_only_for_keywords_it_honours() -> None:
    assert isinstance(_json_dumps({"a": 1}, {"indent": 2, "sort_keys": True}), bytes)
    assert isinstance(_json_dumps({"a": 1}, {}), bytes)
    # a keyword orjson cannot honour, or a value it cannot produce, means plain `json`
    assert isinstance(_json_dumps({"a": 1}, {"separators": (",", ":")}), str)
    assert isinstance(_json_dumps({"a": 1}, {"ensure_ascii": True}), str)
    assert isinstance(_json_dumps({"a": 1}, {"indent": 4}), str)


@needs_orjson
def test_orjson_output_matches_json_byte_for_byte() -> None:
    data = {"b": [1, 2.5, None, True], "a": {"é": "ü"}}
    assert _json_dumps({1: "x", None: "y"}, {}) == json.dumps({1: "x", None: "y"}, separators=(",", ":")).encode()

    for kw in ({}, {"indent": 2}, {"sort_keys": True}, {"indent": 2, "sort_keys": True}):
        fast = _json_dumps(data, dict(kw))
        assert isinstance(fast, bytes)
        # orjson writes compact JSON without spaces when it does not indent.
        separators = None if "indent" in kw else (",", ":")
        assert fast.decode() == json.dumps(data, ensure_ascii=False, separators=separators, **kw)


@needs_orjson
def test_orjson_hands_unknown_types_to_default_like_json() -> None:
    class Thing:
        pass

    with pytest.raises(TypeError):
        _json_dumps(Thing(), {})

    assert _json_dumps(Thing(), {"default": lambda _: "thing"}) == b'"thing"'


@needs_orjson
def test_orjson_parses_only_when_no_keyword_is_given() -> None:
    orjson = pytest.importorskip("orjson")

    with pytest.raises(orjson.JSONDecodeError):
        _json_loads("{bad", {})

    with pytest.raises(json.JSONDecodeError):
        _json_loads("{bad", {"parse_int": int})


# --- removal helpers -------------------------------------------------------

def test_on_exc_remove_folders_ignores_a_vanished_child_but_not_the_root(tmp_path: Path) -> None:
    root = str(tmp_path)
    _on_exc_remove_folders(os.unlink, str(tmp_path / "gone"), FileNotFoundError(), base_path=root)

    with pytest.raises(FileNotFoundError):
        _on_exc_remove_folders(os.rmdir, root, FileNotFoundError(), base_path=root)

    with pytest.raises(PermissionError):
        _on_exc_remove_folders(os.rmdir, root, PermissionError(), base_path=root)


def test_on_exc_remove_folders_unlinks_a_link_and_tolerates_it_vanishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = tmp_path / "link"
    monkeypatch.setattr(_internal, "_is_link", lambda path: str(path) == str(link))
    unlinked: list[str] = []

    def unlink(path: str) -> None:
        unlinked.append(path)
        raise FileNotFoundError(path)

    monkeypatch.setattr(os, "unlink", unlink)

    _on_exc_remove_folders(os.path.islink, str(link), PermissionError(), base_path=str(tmp_path))
    assert unlinked == [str(link)]

    with pytest.raises(PermissionError):  # not a link: the error stands
        _on_exc_remove_folders(os.path.islink, str(tmp_path / "plain"), PermissionError(), base_path=str(tmp_path))


def test_rmtree_removes_a_tree(tmp_path: Path) -> None:
    (tmp_path / "t" / "a").mkdir(parents=True)
    (tmp_path / "t" / "a" / "f").write_text("x", encoding="utf-8")
    _rmtree(tmp_path / "t")
    assert not (tmp_path / "t").exists()


def test_rmtree_tolerates_a_child_that_vanishes_but_reports_a_missing_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = tmp_path / "t"
    tree.mkdir()
    (tree / "f").write_text("x", encoding="utf-8")
    real_unlink = os.unlink

    def vanish(path: Any, *args: Any, **kwargs: Any) -> None:
        real_unlink(path, *args, **kwargs)
        raise FileNotFoundError(path)

    monkeypatch.setattr(os, "unlink", vanish)
    _rmtree(tree)
    assert not tree.exists()

    with pytest.raises(FileNotFoundError):
        _rmtree(tmp_path / "missing")


def test_remove_collects_or_raises_with_the_path_named(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    present = tmp_path / "f"
    present.write_text("x", encoding="utf-8")

    def refuse(path: Path) -> None:
        """Fail like a locked file."""
        raise PermissionError(13, "denied")

    assert _remove(((present, tmp_path / "missing"),), os.unlink, "t", False, False) == [present]

    with caplog.at_level("ERROR"):
        result = _remove((tmp_path / "x",), refuse, "t", True, False)

    assert isinstance(result[0], PermissionError)
    assert result[0].filename == str(tmp_path / "x")
    assert caplog.text == ""

    with caplog.at_level("ERROR"):
        _remove((tmp_path / "x", str(tmp_path / "x")), refuse, "who", True, True)

    assert len(caplog.records) == 1  # deduplicated
    assert caplog.records[0].getMessage() == f"who: could not remove {tmp_path / 'x'}"

    with pytest.raises(PermissionError):
        _remove((tmp_path / "x",), refuse, "t", False, False)


# --- _spill_parts ----------------------------------------------------------

def test_spill_parts_copies_the_removed_end_into_numbered_parts(tmp_path: Path) -> None:
    target = tmp_path / "f.log"
    target.write_bytes(b"0123456789")

    parts = _spill_parts(target, TruncateSide.HEAD, 4, 6, True, False)
    assert [p.name for p in parts] == ["f.log.1", "f.log.2"]
    assert b"".join(p.read_bytes() for p in parts) == b"012345"

    into = tmp_path / "parts"
    parts = _spill_parts(target, TruncateSide.TAIL, 4, 6, into, False)
    assert [p.parent == into for p in parts] == [True, True]
    assert b"".join(p.read_bytes() for p in parts) == b"456789"
    assert target.read_bytes() == b"0123456789"


def test_spill_parts_with_size_zero_uses_a_tenth_of_the_spill(tmp_path: Path) -> None:
    target = tmp_path / "f.log"
    target.write_bytes(bytes(range(25)))

    parts = _spill_parts(target, TruncateSide.HEAD, 0, 25, True, False)
    assert [p.stat().st_size for p in parts] == [3] * 8 + [1]


def test_spill_parts_stops_short_when_the_file_shrinks_under_it(tmp_path: Path) -> None:
    target = tmp_path / "f.log"
    target.write_bytes(b"0123456789")

    # Fewer bytes than announced: the last part is short and nothing after it is written.
    parts = _spill_parts(target, TruncateSide.HEAD, 4, 20, True, False)
    assert [p.read_bytes() for p in parts] == [b"0123", b"4567", b"89"]

    # Nothing at all left to read: no empty part is left behind.
    target.write_bytes(b"01")
    parts = _spill_parts(target, TruncateSide.TAIL, 2, 4, True, False)
    assert parts == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["f.log", "f.log.1", "f.log.2", "f.log.3"]
