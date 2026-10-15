from __future__ import annotations as _annotations

import io
import os
import pickle
from pathlib import Path

import pytest

from pytrove.enums import PickleSafety, TruncateSide
from pytrove.files_tools import _internal, _pickling


def test_next_part_counts_only_numeric_suffixes(tmp_path: Path) -> None:
    for name in ("app.log.1", "app.log.7", "app.log.bak", "other.log.9"):
        (tmp_path / name).write_text("", encoding="utf-8")

    assert _internal._next_part(tmp_path, "app.log") == 8
    assert _internal._next_part(tmp_path, "new.log") == 1
    assert _internal._next_part(tmp_path / "missing", "app.log") == 1


def test_spill_parts_constant() -> None:
    assert _internal._SPILL_PARTS == 10


def test_json_codecs_round_trip_on_either_backend() -> None:
    encoded = _internal._json_dumps({"a": 1}, {})
    assert _internal._json_loads(encoded, {}) == {"a": 1}
    assert _internal._json_dumps({"a": 1}, {"indent": 4}) == '{\n    "a": 1\n}'
    assert _internal._json_loads('{"a": 1.5}', {"parse_float": str}) == {"a": "1.5"}


@pytest.mark.skipif(not _internal.HAS_ORJSON, reason="needs the fastjson extra")
def test_orjson_takes_the_fast_path_only_for_keywords_it_honours() -> None:
    assert isinstance(_internal._json_dumps({"a": 1}, {"indent": 2, "sort_keys": True}), bytes)
    assert isinstance(_internal._json_dumps({"a": 1}, {"ensure_ascii": True}), str)
    assert _internal._ORJSON_COMPAT != 0
    assert _internal._ORJSON_DUMP_KEYS == {"ensure_ascii", "indent", "sort_keys", "default"}


def test_mkdir_options_are_all_optional() -> None:
    assert _internal._MkdirOptions.__required_keys__ == frozenset()


def test_on_exc_remove_folders_ignores_a_vanished_child_but_not_the_root(tmp_path: Path) -> None:
    root = str(tmp_path)
    _internal._on_exc_remove_folders(os.unlink, str(tmp_path / "gone"), FileNotFoundError(), base_path=root)

    with pytest.raises(FileNotFoundError):
        _internal._on_exc_remove_folders(os.rmdir, root, FileNotFoundError(), base_path=root)

    with pytest.raises(PermissionError):
        _internal._on_exc_remove_folders(os.rmdir, root, PermissionError(), base_path=root)


def test_rmtree_removes_a_tree(tmp_path: Path) -> None:
    (tmp_path / "t" / "a").mkdir(parents=True)
    (tmp_path / "t" / "a" / "f").write_text("x", encoding="utf-8")
    _internal._rmtree(tmp_path / "t")
    assert not (tmp_path / "t").exists()


def test_remove_collects_or_raises_with_the_path_named(tmp_path: Path) -> None:
    present = tmp_path / "f"
    present.write_text("x", encoding="utf-8")

    def refuse(path: Path) -> None:
        """Fail like a locked file."""
        raise PermissionError(13, "denied")

    assert _internal._remove(((present, tmp_path / "missing"),), os.unlink, "t", False, False) == [present]
    result = _internal._remove((tmp_path / "x",), refuse, "t", True, False)
    assert isinstance(result[0], PermissionError)
    assert result[0].filename == str(tmp_path / "x")

    with pytest.raises(PermissionError):
        _internal._remove((tmp_path / "x",), refuse, "t", False, False)


def test_spill_parts_copies_the_removed_end_into_numbered_parts(tmp_path: Path) -> None:
    target = tmp_path / "f.log"
    target.write_bytes(b"0123456789")
    parts = _internal._spill_parts(target, TruncateSide.HEAD, 4, 6, True, False)
    assert [p.name for p in parts] == ["f.log.1", "f.log.2"]
    assert b"".join(p.read_bytes() for p in parts) == b"012345"
    assert target.read_bytes() == b"0123456789"


def test_safe_and_unsafe_tables() -> None:
    assert ("builtins", "dict") in _pickling._SAFE_PICKLE_CLASSES
    assert ("builtins", "eval") in _pickling._UNSAFE_PICKLE_CLASSES
    assert "os" in _pickling._UNSAFE_PICKLE_MODULES
    assert not _pickling._SAFE_PICKLE_CLASSES & _pickling._UNSAFE_PICKLE_CLASSES


def test_normalise_global_maps_python_2_names() -> None:
    assert _pickling._normalise_global("__builtin__", "eval") == ("builtins", "eval")
    assert _pickling._normalise_global("copy_reg", "x") == ("copyreg", "x")
    assert _pickling._normalise_global("mine", "Thing") == ("mine", "Thing")


def test_restricted_unpickler_levels() -> None:
    data = pickle.dumps(Path("p"))

    def load(level: PickleSafety, allowed: frozenset[tuple[str, str]], modules: frozenset[str]) -> object:
        """Unpickle `data` at `level`."""
        return _pickling._RestrictedUnpickler(io.BytesIO(data), level, allowed, modules).load()

    assert load(PickleSafety.STRICT, _pickling._SAFE_PICKLE_CLASSES, frozenset()) == Path("p")

    with pytest.raises(pickle.UnpicklingError):
        load(PickleSafety.STRICT, frozenset(), frozenset())

    assert load(PickleSafety.MODULES, frozenset(), frozenset({"pathlib", "pathlib._local"})) == Path("p")
    assert load(PickleSafety.BLOCKLIST, frozenset(), frozenset()) == Path("p")
