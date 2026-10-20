from __future__ import annotations as _annotations

import pytest

from pytrove.text_tools import smart_split


def test_smart_split_basic() -> None:
    assert smart_split("a,b,c", separator=",") == ["a", "b", "c"]


def test_smart_split_calls_a_callable_separator() -> None:
    assert smart_split("a;b", separator=lambda: ";") == ["a", "b"]


def test_smart_split_none_separator_splits_on_whitespace_like_str_split() -> None:
    assert smart_split("a b  c", separator=None) == ["a", "b", "c"]


def test_smart_split_indexing_int_returns_single_item() -> None:
    assert smart_split("a,b,c", 1, separator=",") == "b"


def test_smart_split_indexing_slice_returns_list() -> None:
    assert smart_split("a,b,c,d", slice(1, 3), separator=",") == ["b", "c"]


def test_smart_split_strip_and_remove_spaces() -> None:
    assert smart_split(" a , b ", separator=",", strip=True) == ["a", "b"]
    assert smart_split(" a b , c d ", separator=",", remove_spaces=True) == ["ab", "cd"]


def test_smart_split_filters_raw_parts_before_cleaning() -> None:
    assert smart_split("a, ,b", separator=",", part_filter=bool, strip=True) == ["a", "", "b"]
    assert smart_split("a, ,b", separator=",", part_filter=lambda t: bool(t.strip())) == ["a", "b"]


def test_smart_split_resolves_and_honours_max_split() -> None:
    assert smart_split("1,2,3", separator=",", part_resolver=int) == [1, 2, 3]
    assert smart_split("1,2,3", separator=",", max_split=1) == ["1", "2,3"]
    assert smart_split("1,2,3", 2, int, separator=",") == 3


def test_smart_split_flattens_already_split_parts() -> None:
    assert smart_split(["a", ["b", "c"]], 1, separator=",") == "b"
    assert smart_split(["a,b", ("c",)], separator=",") == ["a,b", "c"]


def test_smart_split_raises_when_the_selected_part_is_filtered_out_or_missing() -> None:
    with pytest.raises(IndexError):
        smart_split("a,b", 0, separator=",", part_filter=lambda t: t == "b")

    with pytest.raises(IndexError):
        smart_split("a,b", 5, separator=",")
