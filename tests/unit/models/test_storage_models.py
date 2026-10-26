from __future__ import annotations as _annotations

import asyncio
import json
import os
import threading
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from pytrove.files_tools import read as files_read
from pytrove.models import JsonContainer
from pytrove.models import storage_models
from pytrove.typings import _KT, _VT

if TYPE_CHECKING:
    from pathlib import Path


def test_json_container_delete_saves_removing_a_none_value(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    container = JsonContainer(path)

    container.set("k", None, save_now=True)
    container.delete("k", save_now=True)

    assert json.loads(path.read_text(encoding="utf-8")) == {}


def test_json_container_loads_on_first_access_and_unloads(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    container = JsonContainer(path)

    assert not container.is_loaded() and container.data is None
    assert container.get("a") == 1
    assert container.get("missing", 0) == 0
    assert container.is_loaded()

    path.write_text('{"a": 2}', encoding="utf-8")
    assert container.get("a") == 1
    container.unload()
    assert container.get("a") == 2


def test_json_container_update_and_save(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    container = JsonContainer(path)

    with pytest.raises(RuntimeError, match="no data loaded"):
        container.save()

    container.update({"a": 1, "b": 2})
    container.set("c", 3)
    container.delete("missing", save_now=True)
    assert not path.exists()
    container.update({}, save_now=True)
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1, "b": 2, "c": 3}


async def test_json_container_async_methods(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    container = JsonContainer(path)

    assert await container.async_get("a") is None
    await container.async_set("a", 1, save_now=True)
    await container.async_update({"b": 2}, save_now=True)
    await container.async_delete("a", save_now=True)
    assert json.loads(path.read_text(encoding="utf-8")) == {"b": 2}

    container.unload()
    await container.async_load()
    assert container.data == {"b": 2}
    container.unload()
    await container.async_set("c", 3)
    await container.async_save()
    container.unload()
    await container.async_delete("b")
    await container.async_update({"d": 4})
    assert container.data == {"c": 3, "d": 4}


def test_json_container_refuses_a_file_without_an_object(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    path.write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(TypeError, match="JSON object"):
        JsonContainer(path).load()


def test_json_container_delete_of_a_missing_key_does_not_save(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    container = JsonContainer(path)
    container.delete("absent", save_now=True)
    assert not path.exists()


def test_json_container_delete_without_save_now_leaves_the_file(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    container = JsonContainer(path)
    container.delete("a")
    assert container.get("a") is None
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}


async def test_json_container_async_delete_of_a_missing_key_does_not_save(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    container = JsonContainer(path)
    await container.async_delete("absent", save_now=True)
    assert not path.exists()


async def test_json_container_async_get_reuses_loaded_data(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    container = JsonContainer(path)
    container.load()
    path.write_text('{"a": 2}', encoding="utf-8")
    assert await container.async_get("a") == 1


async def test_json_container_async_update_loads_the_file_first(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    container = JsonContainer(path)
    await container.async_update({"b": 2}, save_now=True)
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1, "b": 2}


def test_json_container_copy_from_dict_and_str_with_its_init_false_field(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    container = JsonContainer(path)
    container.set("a", [1])

    duplicate = container.copy()
    assert duplicate.data == {"a": [1]} and duplicate.data is not container.data

    rebuilt = JsonContainer.from_dict({"path": path, "data": {"b": 2}})
    assert rebuilt.data == {"b": 2} and rebuilt.path == path
    assert json.loads(str(rebuilt)) == {"path": str(path), "data": {"b": 2}}


class RecordingLock:
    """A lock that records each acquire and release."""

    def __init__(self) -> None:
        """Start with an empty record, not held."""
        self.events: list[str] = []
        self.held = False

    def acquire(self) -> bool:
        """Record the acquire."""
        self.events.append("acquire")
        self.held = True
        return True

    def release(self) -> None:
        """Record the release."""
        self.events.append("release")
        self.held = False


def test_json_container_is_generic_over_its_key_and_value_types() -> None:
    assert JsonContainer.__parameters__ == (_KT, _VT)


def test_json_container_missing_file_loads_as_an_empty_object(tmp_path: Path) -> None:
    container = JsonContainer(tmp_path / "missing.json")
    container.load()
    assert container.data == {}


def test_json_container_load_and_save_forward_their_keywords(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    path.write_text('{"a": 1.5}', encoding="utf-8")
    container = JsonContainer(path)

    container.load(parse_float=Decimal)
    assert container.get("a") == Decimal("1.5") and isinstance(container.get("a"), Decimal)

    container.data = {"b": 1}
    container.save(indent=3)
    assert path.read_text(encoding="utf-8") == json.dumps({"b": 1}, indent=3)


def test_json_container_holds_its_lock_while_reading_and_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "store.json"
    path.write_text("{}", encoding="utf-8")
    lock = RecordingLock()
    container = JsonContainer(path, lock)
    held_during: list[tuple[str, bool]] = []
    real_replace = os.replace

    def recording_open(*args: Any, **kw: Any) -> Any:
        """Record whether the lock is held when the file is opened for reading."""
        held_during.append(("read", lock.held))
        return open(*args, **kw)  # noqa: SIM115 - the caller's `with` closes it.

    def recording_replace(*args: Any, **kw: Any) -> None:
        """Record whether the lock is held when the written file replaces the old one."""
        held_during.append(("write", lock.held))
        real_replace(*args, **kw)

    monkeypatch.setattr(files_read, "open", recording_open, raising=False)
    monkeypatch.setattr(os, "replace", recording_replace)

    container.load()
    assert lock.events == ["acquire", "release"]

    container.save()
    assert lock.events == ["acquire", "release"] * 2
    assert held_during == [("read", True), ("write", True)]


@pytest.mark.parametrize("make_lock", [threading.Lock, asyncio.Lock], ids=["threading", "asyncio"])
def test_json_container_copy_shares_its_lock(tmp_path: Path, make_lock: Any) -> None:
    lock = make_lock()
    container = JsonContainer(tmp_path / "store.json", lock)
    container.data = {"a": [1]}

    duplicate = container.copy()
    assert duplicate.lock is lock
    assert duplicate.data == container.data and duplicate.data is not container.data
    assert duplicate.get("a") is not container.get("a")


async def test_json_container_async_save_refuses_when_nothing_is_loaded(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="no data loaded"):
        await JsonContainer(tmp_path / "store.json").async_save()


async def test_json_container_async_save_writes_a_snapshot_taken_before_the_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "store.json"
    container = JsonContainer(path)
    container.update({"a": [1]})
    real_write_json = storage_models.write_json

    def write_after_a_change(*args: Any, **kw: Any) -> None:
        """Change the live data, as another coroutine might, then write."""
        container.set("b", 2)
        container.get("a").append(2)
        real_write_json(*args, **kw)

    monkeypatch.setattr(storage_models, "write_json", write_after_a_change)
    await container.async_save(indent=2)

    assert json.loads(path.read_text(encoding="utf-8")) == {"a": [1]}
    assert container.data == {"a": [1, 2], "b": 2}
