from __future__ import annotations as _annotations

from collections import defaultdict
from collections.abc import Hashable
from typing import Any, TypeVar

import pytest

from pytrove.data_tools import (
    clean_none_values,
    get_nested_dict_value,
    resolve_json_refs,
    value_to_enum,
)
from pytrove.data_tools._internal import (
    _filled,
    _mapping_filled,
    _none_cleaner,
    _refilled,
    _transform,
    _transform_mapping,
    _MESS,
    _R,
    _RK,
)
from pytrove.errors import ValidationError


def test_get_nested_dict_value_walks_a_custom_separator() -> None:
    assert get_nested_dict_value({"a": {"b": {"c": 3}}}, "a/b/c", sep="/") == 3


def test_get_nested_dict_value_names_a_missing_key() -> None:
    with pytest.raises(KeyError, match="x"):
        get_nested_dict_value({"a": {}}, "a.x")


def test_get_nested_dict_value_refuses_to_walk_into_a_leaf() -> None:
    with pytest.raises(TypeError):
        get_nested_dict_value({"a": 1}, "a.b")


def test_value_to_enum_rejects_an_unknown_side() -> None:
    with pytest.raises(ValidationError, match="must be k or v"):
        value_to_enum({}, [], "x")


def test_clean_none_values_returns_a_non_container_as_is() -> None:
    assert clean_none_values(None) is None
    assert clean_none_values(5) == 5


def test_resolve_json_refs_replaces_references_eagerly() -> None:
    document = {"definitions": {"n": {"type": "integer"}}, "field": {"$ref": "#/definitions/n"}}
    resolved = resolve_json_refs(document)
    assert resolved["field"] == {"type": "integer"}
    assert type(resolved["field"]) is dict


def test_transform_applies_the_function_and_drops_mess() -> None:
    assert list(_transform([1, 2, 3], lambda v: _MESS if v == 2 else v * 10)) == [10, 30]
    assert list(_transform([1, 2])) == [1, 2]


def test_transform_mapping_drops_a_pair_when_either_side_is_mess() -> None:
    data = {"a": 1, "b": 2, "c": 3}
    pairs = _transform_mapping(data, lambda k: _MESS if k == "a" else k, lambda v: _MESS if v == 3 else v)
    assert list(pairs) == [("b", 2)]


def test_filled_detects_only_a_total_loss() -> None:
    assert _filled([1, 2], None, [1])
    assert not _filled([1, 2], None, [])
    assert _filled([], None, [])
    assert _filled([1], None, object())


def test_mapping_filled_detects_only_a_total_loss() -> None:
    assert _mapping_filled({"a": 1}, {"a": 1})
    assert not _mapping_filled({"a": 1}, {})
    assert _mapping_filled({}, {})


def test_refilled_keeps_the_instance_configuration() -> None:
    original = defaultdict(list, a=[1])
    new = _refilled(original, {"b": [2]})
    assert type(new) is defaultdict
    assert new.default_factory is list
    assert dict(new) == {"b": [2]}


def test_refilled_returns_none_when_a_copy_cannot_be_refilled() -> None:
    assert _refilled(range(3), [1]) is None
    assert _refilled((1, 2), [3]) is None


def test_none_cleaner_drops_none_and_cleans_the_rest() -> None:
    assert _none_cleaner(None) is _MESS
    assert _none_cleaner([1, None]) == [1]
    assert _none_cleaner(0) == 0


def test_result_type_variables() -> None:
    assert isinstance(_R, TypeVar)
    assert isinstance(_RK, TypeVar)
    assert _RK.__bound__ is Hashable


def test_mess_is_a_unique_marker() -> None:
    value: Any = _MESS
    assert value is not None
    assert value != object()
