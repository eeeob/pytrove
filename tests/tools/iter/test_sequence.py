from __future__ import annotations as _annotations

import random
from collections import deque
from typing import Any

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
    values = list(range(20))
    result = shuffle(values, random.Random(3))
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
    assert sorted(values) == list(range(5))


def test_dedupe_of_nothing_is_empty() -> None:
    assert dedupe([]) == []
    assert dedupe([], hashable=False) == []


def test_dedupe_compares_by_equality() -> None:
    assert dedupe([1, True, 1.0]) == [1]
    assert dedupe([1, True, 1.0], hashable=False) == [1]


def test_dedupe_without_hashable_consumes_an_iterator_once() -> None:
    values = iter([[1], [1], 2])
    assert dedupe(values, hashable=False) == [[1], 2]
    assert list(values) == []


def test_dedupe_without_hashable_handles_mixed_values() -> None:
    # Hashable values go by hash, unhashable ones by a scan, and a hashable value
    # equal to an earlier unhashable one is still a duplicate.
    assert dedupe([3, {"a": 1}, 3, [1], {"a": 1}, "x", [1], "x"], hashable=False) == [
        3,
        {"a": 1},
        [1],
        "x",
    ]
    assert dedupe([{1}, frozenset({1})], hashable=False) == [{1}]
    assert dedupe([frozenset({1}), {1}], hashable=False) == [frozenset({1})]


def test_pad_list_pads_a_shorter_list_when_exact() -> None:
    assert pad_list([1], 3, exact=True, default=0) == [1, 0, 0]


def test_pad_list_at_the_edges_of_length() -> None:
    assert pad_list([1, 2], 0) == [1, 2]
    assert pad_list([1, 2], 0, exact=True) == []
    assert pad_list([1, 2], 2, exact=True) == [1, 2]
    assert pad_list([], 2) == [None, None]


def test_pad_list_takes_the_default_positionally() -> None:
    assert pad_list([1], 3, False, 0) == [1, 0, 0]


@pytest.mark.parametrize("exact", [False, True])
def test_pad_list_refuses_a_negative_length(exact: bool) -> None:
    values = [1, 2, 3]

    with pytest.raises(ValueError, match="must not be negative, not -1"):
        pad_list(values, -1, exact=exact)

    assert values == [1, 2, 3]


def test_shuffle_of_an_empty_list_is_that_list() -> None:
    values: list[int] = []
    assert shuffle(values) is values


@pytest.mark.parametrize("source", [(1, 2, 3, 4), {1, 2, 3, 4}])
def test_shuffle_copies_a_tuple_or_set_and_leaves_it_alone(source: Any) -> None:
    before = type(source)(source)
    result = shuffle(source)

    assert type(result) is list
    assert sorted(result) == [1, 2, 3, 4]
    assert source == before


def test_shuffle_draws_from_the_given_generator() -> None:
    first = shuffle(list(range(20)), random.Random(7))
    second = shuffle(list(range(20)), random.Random(7))
    assert first == second

    expected = list(range(20))
    random.Random(7).shuffle(expected)
    assert first == expected


def test_shuffle_without_a_generator_uses_the_global_one(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[int]] = []
    monkeypatch.setattr(random, "shuffle", calls.append)
    values = [1, 2]

    shuffle(values)

    assert calls == [values]
