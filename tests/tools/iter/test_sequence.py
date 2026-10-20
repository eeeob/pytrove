from __future__ import annotations as _annotations

import random
from collections import deque

import pytest

from pytrove.iter_tools import dedupe, pad_list, shuffle


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
