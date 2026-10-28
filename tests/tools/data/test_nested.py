"""`data_tools.nested`: dotted key paths and JSON `$ref` resolution."""

from __future__ import annotations as _annotations

import types

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


@pytest.mark.parametrize("leaf", [[1, 2], "xyz"])
def test_get_nested_dict_value_refuses_to_walk_into_a_list_or_str(leaf: object) -> None:
    with pytest.raises(TypeError):
        get_nested_dict_value({"a": leaf}, "a.0")  # type: ignore[dict-item]  # The wrong shape is the point.


def test_get_nested_dict_value_with_an_empty_path_looks_up_the_empty_key() -> None:
    assert get_nested_dict_value({"": 1}, "") == 1

    with pytest.raises(KeyError):
        get_nested_dict_value({"a": 1}, "")


def test_get_nested_dict_value_splits_a_key_holding_the_separator() -> None:
    with pytest.raises(KeyError, match="'a'"):
        get_nested_dict_value({"a.b": 1}, "a.b")

    assert get_nested_dict_value({"a.b": 1}, "a.b", sep="/") == 1


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


def test_get_nested_dict_key_checks_the_key_count_at_every_level() -> None:
    with pytest.raises(TypeError, match="must be 1 not 2, at 'a'"):
        get_nested_dict_key({"a": {"b": True, "c": True}})

    with pytest.raises(TypeError, match="must be 1 not 0, at 'a.b'"):
        get_nested_dict_key({"a": {"b": {}}})


def test_get_nested_dict_key_walks_a_non_dict_mapping() -> None:
    inner = types.MappingProxyType({"b": True})
    assert get_nested_dict_key({"a": inner}) == "a.b"  # type: ignore[dict-item]  # Any mapping is walked.


def test_get_nested_dict_key_is_the_inverse_even_for_odd_keys() -> None:
    path = get_nested_dict_key({"": {"b": True}})
    assert path == ".b"
    assert get_nested_dict_value({"": {"b": True}}, path) is True

    assert get_nested_dict_key({1: True}) == "1"  # type: ignore[dict-item]  # A non-str key is joined as its `str`.


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


def test_resolve_json_refs_resolves_a_relative_ref_against_base_uri() -> None:
    pytest.importorskip("jsonref")
    seen: list[str] = []

    def loader(uri: str) -> object:
        seen.append(uri)
        return {"x": 5}

    resolved = resolve_json_refs(
        {"field": {"$ref": "other.json#/x"}},
        base_uri="https://example.com/schemas/root.json",
        loader=loader,
    )

    assert resolved == {"field": 5}
    assert seen == ["https://example.com/schemas/other.json"]
