from __future__ import annotations as _annotations

from collections import UserString
from enum import Enum
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


def test_to_frozenset_deduplicates_into_a_frozenset() -> None:
    result = to_frozenset([1, 1, 2])
    assert type(result) is frozenset
    assert result == frozenset({1, 2})


def test_to_list_wraps_a_user_string_like_a_str() -> None:
    text = UserString("ab")
    assert to_list(text) == [text]
    assert to_tuple(text) == (text,)


class _Shade(Enum):
    DARK = 1


class _AwaitableList(list):  # type: ignore[type-arg]  # Only the awaitable shape matters here.
    """A list that is also awaitable, so `NotContainer` makes it a single value."""

    def __await__(self) -> Any:
        return iter(())


_CONVERTERS = [to_list, to_tuple, to_set, to_frozenset]


@pytest.mark.parametrize("convert", _CONVERTERS)
def test_converters_take_an_iterator(convert: Any) -> None:
    assert convert(iter([1, 2])) == convert([1, 2])
    assert convert(v for v in (1, 2)) == convert([1, 2])


@pytest.mark.parametrize("convert", _CONVERTERS)
@pytest.mark.parametrize(
    "single", [b"ab", bytearray(b"ab"), memoryview(b"ab"), _Shade, _AwaitableList([1])]
)
def test_converters_wrap_a_not_container_as_a_single_value(convert: Any, single: Any) -> None:
    try:
        expected = convert([single])
    except TypeError:  # unhashable: the set converters refuse it either way
        with pytest.raises(TypeError):
            convert(single)
    else:
        assert convert(single) == expected


@pytest.mark.parametrize("convert", [to_list, to_tuple])
def test_converters_do_not_flatten(convert: Any) -> None:
    assert list(convert([[1], (2,)])) == [[1], (2,)]


@pytest.mark.parametrize("convert", [to_set, to_frozenset])
def test_set_converters_refuse_unhashable_items(convert: Any) -> None:
    with pytest.raises(TypeError):
        convert([[1]])


def test_to_set_and_to_frozenset_wrap_a_user_string() -> None:
    text = UserString("ab")
    assert to_set(text) == {text}
    assert to_frozenset(text) == frozenset({text})
