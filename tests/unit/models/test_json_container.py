from __future__ import annotations as _annotations

import json
from pathlib import Path

import pytest

from pytrove.models import JsonContainer


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

    assert not container.is_loaded() and container.data is object
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
