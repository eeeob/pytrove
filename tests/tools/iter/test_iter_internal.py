from __future__ import annotations as _annotations

from collections.abc import MutableSequence
from typing import Any, TypeVar

from pytrove.iter_tools import to_list
from pytrove.iter_tools._internal import _MS, _items


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


def test_items_of_a_mapping_is_the_mapping_so_converters_take_its_keys() -> None:
    mapping = {"a": 1}
    assert _items(mapping) is mapping
    assert to_list(mapping) == ["a"]


def test_items_of_an_iterator_is_consumed_once() -> None:
    values = iter([1, 2])
    assert tuple(_items(values)) == (1, 2)
    assert tuple(values) == ()


def test_items_wraps_bytes_as_a_single_value() -> None:
    assert _items(b"ab") == (b"ab",)
