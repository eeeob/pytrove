from __future__ import annotations as _annotations

import pytest

from pytrove.text_tools import (
    clean_spaces,
    smart_split,
    split_part,
    to_pascal_case,
    to_snake_case,
    to_str,
)


def test_to_str_converts_only_plain_scalars() -> None:
    assert to_str(12) == "12"
    assert to_str(1.5) == "1.5"
    assert to_str(True) is True
    assert to_str(None) is None
    values = [1]
    assert to_str(values) is values
    assert to_str("x") == "x"


def test_clean_spaces_can_keep_line_breaks() -> None:
    assert clean_spaces(" a \t b\n c ") == "abc"
    assert clean_spaces(" a \t b\n c ", with_lines=False) == "ab\nc"
    assert clean_spaces(12) == "12"


@pytest.mark.parametrize("value", [None, True, [1], {"a": 1}])
def test_clean_spaces_refuses_what_to_str_leaves_unconverted(value: object) -> None:
    with pytest.raises(TypeError, match="clean_spaces: text must be a str"):
        clean_spaces(value)


def test_split_part_selects_and_cleans_a_part() -> None:
    assert split_part("a, b ,c", ",", 1) == "b"
    assert split_part("a, b c ,d", ",", 1, remove_spaces=True) == "bc"
    assert split_part("a, b ,c", ",", 1, strip=False) == " b "
    assert split_part("a,b,c", ",") == "a"


def test_split_part_out_of_range_returns_the_value_or_the_default() -> None:
    assert split_part("a,b", ",", 5) == "a,b"
    assert split_part("a,b", ",", 5, default=None) is None
    assert split_part("a,b", ",", 5, default="x") == "x"


def test_split_part_counts_a_negative_part_from_the_end() -> None:
    assert split_part("a, b ,c ", ",", -1) == "c"
    assert split_part("a,b", ",", -3) == "a,b"


def test_split_part_refuses_an_empty_separator() -> None:
    with pytest.raises(ValueError, match="empty separator"):
        split_part("a,b", "")


@pytest.mark.parametrize("part", [-2, -1, 0, 1])
@pytest.mark.parametrize("strip", [True, False])
@pytest.mark.parametrize("remove_spaces", [True, False])
def test_split_part_is_smart_split_with_one_index(
    part: int, strip: bool, remove_spaces: bool
) -> None:
    text = " a b , c\td \n"
    expected = smart_split(text, part, strip=strip, remove_spaces=remove_spaces, separator=",")
    assert split_part(text, ",", part, strip, remove_spaces) == expected


@pytest.mark.parametrize(
    ("text", "snake", "pascal"),
    [
        ("camelCase", "camel_case", "CamelCase"),
        ("PascalCase", "pascal_case", "PascalCase"),
        ("getHTTPResponse", "get_http_response", "GetHttpResponse"),
        ("already_snake", "already_snake", "AlreadySnake"),
        ("version2Name", "version2_name", "Version2Name"),
        ("__dunder__", "__dunder__", "Dunder"),
    ],
)
def test_case_conversions(text: str, snake: str, pascal: str) -> None:
    assert to_snake_case(text) == snake
    assert to_pascal_case(text) == pascal
