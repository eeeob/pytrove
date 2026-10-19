from __future__ import annotations as _annotations

import pytest

from pytrove.mongo_tools import MongoIndex, HAS_PYMONGO

needs_pymongo = pytest.mark.skipif(not HAS_PYMONGO, reason="needs the mongo extra")


@needs_pymongo
def test_mongo_index_round_trips_and_compares_by_definition() -> None:
    index = MongoIndex.from_dict({"v": 2, "name": "ignored", "key": {"a": 1, "b": -1}, "unique": True})
    assert index.key == "a_b"
    assert index.name == "a_1_b_-1"
    assert index == MongoIndex({"a": 1, "b": -1}, unique=True)
    assert hash(index) == hash(MongoIndex({"a": 1, "b": -1}, unique=True))
    assert index != MongoIndex({"a": 1})
    assert index.__eq__(object()) is NotImplemented


@needs_pymongo
def test_mongo_index_from_dict_requires_a_key() -> None:
    with pytest.raises(KeyError):
        MongoIndex.from_dict({"unique": True})


@pytest.mark.skipif(HAS_PYMONGO, reason="the mongo extra is installed")
def test_mongo_index_names_the_mongo_extra_when_pymongo_is_missing() -> None:
    with pytest.raises(ImportError, match=r"pytrove\[mongo\]"):
        MongoIndex({"a": 1})

    with pytest.raises(ImportError, match=r"pytrove\[mongo\]"):
        MongoIndex.from_dict({"key": {"a": 1}})
