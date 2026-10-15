from __future__ import annotations as _annotations

from pytrove.mongo_tools import MongoIndex


def test_mongo_index_round_trips_and_compares_by_definition() -> None:
    index = MongoIndex.from_dict({"v": 2, "name": "ignored", "key": {"a": 1, "b": -1}, "unique": True})
    assert index.key == "a_b"
    assert index.name == "a_1_b_-1"
    assert index == MongoIndex({"a": 1, "b": -1}, unique=True)
    assert hash(index) == hash(MongoIndex({"a": 1, "b": -1}, unique=True))
    assert index != MongoIndex({"a": 1})
    assert index.__eq__(object()) is NotImplemented
