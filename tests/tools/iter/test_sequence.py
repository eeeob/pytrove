from __future__ import annotations as _annotations

import random
from collections import deque
from collections.abc import MutableSequence
from typing import Any, TypeVar

import pytest

from pytrove.iter_tools import dedupe, pad_list, shuffle, to_frozenset, to_list, to_set, to_tuple
from pytrove.iter_tools._internal import _MS, _items


@pytest.mark.parametrize(("convert", "single", "empty"), [
    (to_list, [5], []),
    (to_tuple, (5,), ()),
    (to_set, {5}, set()),
    (to_frozenset, frozenset({5}), frozenset()),
])
def test_converters_wrap_a_single_value_and_empty_none(convert: Any, single: Any, empty: Any) -> None:
    assert convert(5) == single
    assert convert(None) == empty
    assert convert("ab") == convert(["ab"])


def test_dedupe_keeps_first_seen_order() -> None:
    assert dedupe([3, 1, 3, 2, 1]) == [3, 1, 2]
    assert dedupe(iter("abca")) == ["a", "b", "c"]


def test_dedupe_handles_unhashable_values_when_told() -> None:
    assert dedupe([{"a": 1}, [1], {"a": 1}, [1]], hashable=False) == [{"a": 1}, [1]]

    with pytest.raises(TypeError):
        dedupe([{"a": 1}])


def test_pad_list_pads_in_place_and_returns_the_same_list() -> None:
    values = [1, 2]
    result = pad_list(values, 4, default=0)
    assert result is values
    assert values == [1, 2, 0, 0]


def test_pad_list_leaves_a_longer_list_alone_unless_exact() -> None:
    assert pad_list([1, 2, 3], 2) == [1, 2, 3]
    assert pad_list([1, 2, 3], 2, exact=True) == [1, 2]
    assert pad_list([1], 1) == [1]


def test_shuffle_shuffles_a_mutable_sequence_in_place() -> None:
    random.seed(3)
    values = list(range(20))
    result = shuffle(values)
    assert result is values
    assert sorted(values) == list(range(20))
    assert values != list(range(20))


def test_shuffle_copies_any_other_iterable_into_a_list() -> None:
    result = shuffle(range(10))
    assert isinstance(result, list)
    assert sorted(result) == list(range(10))
    assert shuffle(()) == []


def test_shuffle_keeps_a_deque_a_deque() -> None:
    values = deque(range(5))
    assert shuffle(values) is values


def test_ms_is_bound_to_mutable_sequences() -> None:
    assert isinstance(_MS, TypeVar)
    assert _MS.__bound__ == MutableSequence[Any]


def test_items_of_none_is_empty() -> None:
    assert tuple(_items(None)) == ()


def test_items_of_a_container_is_the_container_itself() -> None:
    values = [1, 2, 3]
    assert _items(values) is values


def test_items_wraps_a_single_value() -> None:
    assert _items(5) == (5,)
    assert _items("abc") == ("abc",)
