from __future__ import annotations as _annotations

import enum

import pytest

from pytrove.enums import StrEnum
from pytrove.text_tools import (
    clean_spaces,
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


class _Color(enum.Enum):
    RED = 1


class _Mode(StrEnum):
    FAST = "fast"


@pytest.mark.parametrize(
    "value", [b"ab", bytearray(b"ab"), memoryview(b"ab"), (1,), {1}, {"a": 1}, _Mode.FAST]
)
def test_to_str_leaves_bytes_strings_and_containers_unchanged(value: object) -> None:
    assert to_str(value) is value


def test_to_str_turns_an_enum_member_into_its_str() -> None:
    assert to_str(_Color.RED) == "_Color.RED"


def test_clean_spaces_can_keep_line_breaks() -> None:
    assert clean_spaces(" a \t b\n c ") == "abc"
    assert clean_spaces(" a \t b\n c ", include_newlines=False) == "ab\nc"
    assert clean_spaces(12) == "12"


def test_clean_spaces_edge_cases() -> None:
    assert clean_spaces("") == ""
    assert clean_spaces("a\u00a0b\u2003c") == "abc"
    # Only `\n` survives `include_newlines=False`; `\r` and the rest go.
    assert clean_spaces("a\r\nb\x0bc\x0cd\x85e", include_newlines=False) == "a\nbcde"


@pytest.mark.parametrize("value", [None, True, [1], {"a": 1}, b"a b"])
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
    assert split_part("a,b", ",", 1, default="x") == "b"


def test_split_part_counts_a_negative_part_from_the_end() -> None:
    assert split_part("a, b ,c ", ",", -1) == "c"
    assert split_part("a,b", ",", -3) == "a,b"


def test_split_part_refuses_an_empty_separator() -> None:
    with pytest.raises(ValueError, match="empty separator"):
        split_part("a,b", "")


@pytest.mark.parametrize(
    ("part", "strip", "remove_spaces", "expected"),
    [
        (0, True, False, "a b"),
        (0, False, False, " a b "),
        (0, False, True, "ab"),
        (0, True, True, "ab"),
        (1, True, False, "c\td"),
        (1, False, False, " c\td \n"),
        (1, False, True, "cd"),
        (-1, True, False, "c\td"),
        (-2, False, False, " a b "),
    ],
)
def test_split_part_cleans_the_selected_part(
    part: int, strip: bool, remove_spaces: bool, expected: str
) -> None:
    assert split_part(" a b , c\td \n", ",", part, strip, remove_spaces) == expected


@pytest.mark.parametrize(
    ("text", "snake", "pascal"),
    [
        ("camelCase", "camel_case", "CamelCase"),
        ("PascalCase", "pascal_case", "PascalCase"),
        ("getHTTPResponse", "get_http_response", "GetHttpResponse"),
        ("already_snake", "already_snake", "AlreadySnake"),
        ("version2Name", "version2_name", "Version2Name"),
        ("__dunder__", "__dunder__", "Dunder"),
        ("", "", ""),
        ("HTTP", "http", "Http"),
        ("getHTTP", "get_http", "GetHttp"),
        ("my_Var", "my_var", "MyVar"),
        ("snake_Case_X", "snake_case_x", "SnakeCaseX"),
        ("HTTP_Response", "http_response", "HttpResponse"),
        ("user_2fa", "user_2fa", "User2fa"),
        ("2fa_code", "2fa_code", "2faCode"),
        # Only `_` and case changes separate words: a `-` stays inside one.
        ("user-id", "user-id", "User-id"),
        # Only ASCII capitals start a word.
        ("camelÄpfel", "cameläpfel", "Cameläpfel"),
    ],
)
def test_case_conversions(text: str, snake: str, pascal: str) -> None:
    assert to_snake_case(text) == snake
    assert to_pascal_case(text) == pascal
