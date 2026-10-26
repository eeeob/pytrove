from __future__ import annotations as _annotations

import pytest

from pytrove.mongo_tools import MongoIndex, HAS_PYMONGO

needs_pymongo = pytest.mark.skipif(not HAS_PYMONGO, reason="needs the mongo extra")


@needs_pymongo
def test_mongo_index_round_trips_and_compares_by_definition() -> None:
    index = MongoIndex.from_dict(
        {"v": 2, "name": "a_1_b_-1", "key": {"a": 1, "b": -1}, "unique": True}
    )
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


@needs_pymongo
def test_mongo_index_ignores_the_order_of_its_options() -> None:
    first = MongoIndex({"a": 1}, unique=True, sparse=True)
    second = MongoIndex({"a": 1}, sparse=True, unique=True)

    assert first == second
    assert hash(first) == hash(second)
    assert len({first, second}) == 1


@needs_pymongo
def test_mongo_index_keeps_the_order_of_its_key() -> None:
    assert MongoIndex([("a", 1), ("b", 1)]) != MongoIndex([("b", 1), ("a", 1)])


@needs_pymongo
def test_mongo_index_differs_by_an_option_value() -> None:
    assert MongoIndex({"a": 1}, unique=True) != MongoIndex({"a": 1}, unique=False)
    assert MongoIndex({"a": 1}, name="x") != MongoIndex({"a": 1})


@needs_pymongo
def test_mongo_index_from_dict_reads_the_index_information_shape() -> None:
    # An `index_information()` entry: its name is the outer key, not a field.
    info = {"v": 2, "key": [("a", 1), ("b", -1)], "sparse": True}

    assert MongoIndex.from_dict(info) == MongoIndex([("a", 1), ("b", -1)], sparse=True)


@needs_pymongo
def test_mongo_index_from_dict_keeps_a_custom_name() -> None:
    # A `list_indexes()` document carries its `name`.
    index = MongoIndex.from_dict({"v": 2, "key": [("a", 1)], "name": "by_a", "unique": True})

    assert index.name == "by_a"
    assert index == MongoIndex({"a": 1}, name="by_a", unique=True)


@needs_pymongo
def test_mongo_index_equals_its_server_copy_with_son_options() -> None:
    SON = pytest.importorskip("bson.son").SON

    declared = MongoIndex({"a": 1}, partialFilterExpression={"x": {"$gt": [1, 2]}})
    server = MongoIndex.from_dict(
        {
            "v": 2,
            "key": SON([("a", 1)]),
            "name": "a_1",
            "partialFilterExpression": SON([("x", SON([("$gt", (1, 2))]))]),
        }
    )

    assert declared == server
    assert hash(declared) == hash(server)
    assert declared != MongoIndex({"a": 1}, partialFilterExpression={"x": 2})


@needs_pymongo
def test_mongo_index_from_dict_leaves_its_argument_unchanged() -> None:
    info = {"v": 2, "key": [("a", 1)], "name": "a_1", "unique": True}
    copy = dict(info)

    MongoIndex.from_dict(info)

    assert info == copy
