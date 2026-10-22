"""`data_tools.nested`: dotted key paths and JSON `$ref` resolution."""

from __future__ import annotations as _annotations

import pytest

from pytrove.data_tools import get_nested_dict_key, get_nested_dict_value, resolve_json_refs


def test_get_nested_dict_value_walks_the_path() -> None:
    assert get_nested_dict_value({"a": {"b": 1}}, "a.b") == 1
    assert get_nested_dict_value({"a": {"b": {"c": 3}}}, "a/b/c", sep="/") == 3
    assert get_nested_dict_value({"a": 1}, "a") == 1


def test_get_nested_dict_value_names_a_missing_key() -> None:
    with pytest.raises(KeyError, match="x"):
        get_nested_dict_value({"a": {}}, "a.x")


def test_get_nested_dict_value_refuses_to_walk_into_a_leaf() -> None:
    with pytest.raises(TypeError):
        get_nested_dict_value({"a": 1}, "a.b")


def test_get_nested_dict_key_accepts_true_and_one() -> None:
    assert get_nested_dict_key({"a": {"b": True}}) == "a.b"
    assert get_nested_dict_key({"a": {"b": 1}}) == "a.b"
    assert get_nested_dict_key({"a": {"b": {"c": True}}}, sep="/") == "a/b/c"
    assert get_nested_dict_key({"a": True}) == "a"


def test_get_nested_dict_key_rejects_an_invalid_leaf() -> None:
    with pytest.raises(TypeError, match="must be True or 1"):
        get_nested_dict_key({"a": {"b": 2}})

    with pytest.raises(TypeError, match="'a.b'"):
        get_nested_dict_key({"a": {"b": 0}})


def test_get_nested_dict_key_rejects_more_or_less_than_one_branch() -> None:
    with pytest.raises(TypeError, match="must be 1 not 2"):
        get_nested_dict_key({"a": True, "b": True})

    with pytest.raises(TypeError, match="must be 1 not 0"):
        get_nested_dict_key({})


def test_resolve_json_refs_replaces_references_eagerly() -> None:
    jsonref = pytest.importorskip("jsonref")
    document = {"definitions": {"n": {"type": "integer"}}, "field": {"$ref": "#/definitions/n"}}

    resolved = resolve_json_refs(document)

    assert resolved["field"] == {"type": "integer"}
    assert type(resolved["field"]) is dict  # `proxies=False`

    with pytest.raises(jsonref.JsonRefError):  # `lazy_load=False`
        resolve_json_refs({"field": {"$ref": "#/missing"}})


def test_resolve_json_refs_forwards_keywords() -> None:
    jsonref = pytest.importorskip("jsonref")
    document = {"n": 1, "field": {"$ref": "#/n"}}

    assert isinstance(resolve_json_refs(document, proxies=True)["field"], jsonref.JsonRef)
    # with proxies, `lazy_load=True` defers the failure to the first access
    lazy = resolve_json_refs({"field": {"$ref": "#/missing"}}, proxies=True, lazy_load=True)

    with pytest.raises(jsonref.JsonRefError):
        str(lazy["field"])


def test_resolve_json_refs_names_the_extra_when_jsonref_is_missing() -> None:
    try:
        import jsonref  # noqa: F401, PLC0415 - probes whether the optional `jsonref` is installed
    except ImportError:
        pass
    else:
        pytest.skip("jsonref is installed")

    with pytest.raises(ImportError, match=r"pytrove\[json\]"):
        resolve_json_refs({})
