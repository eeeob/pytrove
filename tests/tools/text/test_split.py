from __future__ import annotations as _annotations

from typing import Any

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


@pytest.mark.parametrize(
    ("args", "kwargs", "expected"),
    [
        # Empty text: `str.split` semantics.
        (("",), {"separator": ","}, [""]),
        (("",), {"separator": None}, []),
        # Negative and stepped indexing.
        (("a,b,c,d,e", -2), {"separator": ","}, "d"),
        (("a,b,c,d,e", slice(-2, None)), {"separator": ","}, ["d", "e"]),
        (("a,b,c,d,e", slice(None, None, 2)), {"separator": ","}, ["a", "c", "e"]),
        (("a,b,c,d,e", slice(None, None, -1)), {"separator": ","}, ["e", "d", "c", "b", "a"]),
        # The slice runs on the raw parts, before the filter.
        (("a,,b,c", slice(0, 2)), {"part_filter": bool, "separator": ","}, ["a"]),
        # `max_split` limits a string, and is ignored for a container.
        (("a,b,c",), {"max_split": 0, "separator": ","}, ["a,b,c"]),
        ((["a", ["b", "c"]],), {"max_split": 0, "separator": ","}, ["a", "b", "c"]),
        # A container drops `None` leaves and gives a mapping's keys.
        ((["a", None, "b"], 1), {"separator": ","}, "b"),
        (({"k": "v"},), {"separator": ","}, ["k"]),
        # `remove_spaces` wins over `strip`.
        ((" a b , c ",), {"strip": True, "remove_spaces": True, "separator": ","}, ["ab", "c"]),
        # A resolver on a slice.
        (("1,2,3", slice(1, None), int), {"separator": ","}, [2, 3]),
        # A callable separator with indexing, and one returning `None`.
        (("a;b", 1), {"separator": lambda: ";"}, "b"),
        (("a b,c", 1), {"separator": lambda: None}, "b,c"),
        # Every parameter positionally.
        (("a, b", 1, None, True), {"separator": ","}, "b"),
        (("1,2", None, int), {"separator": ","}, [1, 2]),
    ],
)
def test_smart_split_cases(args: tuple[Any, ...], kwargs: dict[str, Any], expected: object) -> None:
    assert smart_split(*args, **kwargs) == expected


def test_smart_split_refuses_an_empty_separator() -> None:
    with pytest.raises(ValueError, match="empty separator"):
        smart_split("a,b", separator="")


def test_smart_split_propagates_a_resolver_error() -> None:
    with pytest.raises(ValueError, match="invalid literal"):
        smart_split("1,x", separator=",", part_resolver=int)
