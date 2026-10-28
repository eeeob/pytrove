from __future__ import annotations as _annotations

from collections import UserString
from typing import Any

import pytest

from pytrove.iter_tools import to_frozenset, to_list, to_set, to_tuple


@pytest.mark.parametrize(
    ("convert", "single", "empty"),
    [
        (to_list, [5], []),
        (to_tuple, (5,), ()),
        (to_set, {5}, set()),
        (to_frozenset, frozenset({5}), frozenset()),
    ],
)
def test_converters_wrap_a_single_value_and_empty_none(
    convert: Any, single: Any, empty: Any
) -> None:
    assert convert(5) == single
    assert convert(None) == empty
    assert convert("ab") == convert(["ab"])


def test_to_list_with_mapping_returns_keys() -> None:
    assert to_list({"a": 1, "b": 2}) == ["a", "b"]


def test_to_tuple_preserves_order() -> None:
    assert to_tuple([3, 1, 2]) == (3, 1, 2)


def test_to_set_deduplicates() -> None:
    assert to_set([1, 1, 2, 2, 3]) == {1, 2, 3}


def test_to_frozenset_is_immutable_type() -> None:
    result = to_frozenset([1, 2])
    assert isinstance(result, frozenset)


def test_to_collection_helpers() -> None:
    assert to_list(None) == []
    assert to_list(5) == [5]
    assert to_list([1, 2]) == [1, 2]

    assert to_set(None) == set()
    assert to_set([1, 1, 2]) == {1, 2}

    assert to_tuple(None) == ()
    assert to_tuple(5) == (5,)

    assert to_frozenset(None) == frozenset()
    assert to_frozenset([1, 1, 2]) == frozenset({1, 2})


def test_to_list_wraps_a_user_string_like_a_str() -> None:
    text = UserString("ab")
    assert to_list(text) == [text]
    assert to_tuple(text) == (text,)
