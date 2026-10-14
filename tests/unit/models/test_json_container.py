import json
from pytrove.models import JsonContainer


def test_json_container_delete_saves_removing_a_none_value(tmp_path):
    path = tmp_path / "store.json"
    container = JsonContainer(path)

    container.set("k", None, save_now=True)
    container.delete("k", save_now=True)

    assert json.loads(path.read_text(encoding="utf-8")) == {}
