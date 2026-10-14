from __future__ import annotations as _annotations

import pytest

from pytrove.text_tools import (
    chunk_text,
    clean_spaces,
    numbering,
    smart_split,
    split_part,
    to_pascal_case,
    to_snake_case,
    to_str,
)
from pytrove.text_tools._internal import _smart_split_part, _SNAKE1_PATTERN, _SNAKE2_PATTERN


def test_to_str_converts_only_plain_scalars() -> None:
    assert to_str(12) == "12"
    assert to_str(1.5) == "1.5"
    assert to_str(True) is True
    assert to_str(None) is None
    values = [1]
    assert to_str(values) is values


def test_clean_spaces_can_keep_line_breaks() -> None:
    assert clean_spaces(" a \t b\n c ") == "abc"
    assert clean_spaces(" a \t b\n c ", with_lines=False) == "ab\nc"
    assert clean_spaces(12) == "12"


def test_split_part_selects_and_cleans_a_part() -> None:
    assert split_part("a, b ,c", ",", 1) == "b"
    assert split_part("a, b c ,d", ",", 1, remove_spaces=True) == "bc"
    assert split_part("a, b ,c", ",", 1, strip=False) == " b "


def test_split_part_out_of_range_returns_the_value_or_the_default() -> None:
    assert split_part("a,b", ",", 5) == "a,b"
    assert split_part("a,b", ",", 5, default=None) is None
    assert split_part("a,b", ",", 5, default="x") == "x"


@pytest.mark.parametrize(("text", "snake", "pascal"), [
    ("camelCase", "camel_case", "CamelCase"),
    ("PascalCase", "pascal_case", "PascalCase"),
    ("getHTTPResponse", "get_http_response", "GetHttpResponse"),
    ("already_snake", "already_snake", "AlreadySnake"),
    ("version2Name", "version2_name", "Version2Name"),
])
def test_case_conversions(text: str, snake: str, pascal: str) -> None:
    assert to_snake_case(text) == snake
    assert to_pascal_case(text) == pascal


def test_snake_patterns() -> None:
    assert _SNAKE1_PATTERN.sub(r"\1_\2", "getHTTPResponse") == "getHTTP_Response"
    assert _SNAKE2_PATTERN.sub(r"\1_\2", "getHTTP") == "get_HTTP"


def test_chunk_text_breaks_at_a_late_space_but_not_an_early_one() -> None:
    assert chunk_text("aaaa bbbb", max_length=6) == ["aaaa", "bbbb"]
    assert chunk_text("a bbbbbbbbbbbbbbbbbbbbbbbbbbb", max_length=20) == ["a bbbbbbbbbbbbbbbbbb", "bbbbbbbbb"]


def test_chunk_text_drops_blank_pieces() -> None:
    assert chunk_text("abc\n\n\n   \ndef", max_length=4) == ["abc", "def"]


def test_numbering_a_mapping_with_a_custom_parser() -> None:
    assert numbering({"a": 1}, start=3, line_parser=lambda k, v, n: f"{n}:{k}={v}") == "3:a=1"
    assert numbering({"a": 1, "b": 2}, line_sep=None) == ["1. a - 1", "2. b - 2"]


def test_smart_split_filters_raw_parts_before_cleaning() -> None:
    assert smart_split("a, ,b", separator=",", part_filter=bool, strip=True) == ["a", "", "b"]
    assert smart_split("a, ,b", separator=",", part_filter=lambda t: bool(t.strip())) == ["a", "b"]


def test_smart_split_resolves_and_honours_max_split() -> None:
    assert smart_split("1,2,3", separator=",", part_resolver=int) == [1, 2, 3]
    assert smart_split("1,2,3", separator=",", max_split=1) == ["1", "2,3"]


def test_smart_split_accepts_a_callable_separator_and_split_parts() -> None:
    assert smart_split("a|b", separator=lambda: "|") == ["a", "b"]
    assert smart_split(["a", ["b", "c"]], 1, separator=",") == "b"


def test_smart_split_raises_when_the_selected_part_is_filtered_out() -> None:
    with pytest.raises(IndexError):
        smart_split("a,b", 0, separator=",", part_filter=lambda t: t == "b")


def test_smart_split_part_reports_whether_a_part_is_kept() -> None:
    assert _smart_split_part(" x ", None, True, False, None) == (True, "x")
    assert _smart_split_part(" x y ", None, False, True, None) == (True, "xy")
    assert _smart_split_part("5", None, False, False, int) == (True, 5)
    assert _smart_split_part("5", lambda t: False, False, False, int) == (False, None)
