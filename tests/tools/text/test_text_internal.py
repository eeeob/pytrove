from __future__ import annotations as _annotations

from pytrove.text_tools._internal import (
    _cut_piece,
    _smart_split_part,
    _SNAKE1_PATTERN,
    _SNAKE2_PATTERN,
)


def test_cut_piece_prefers_a_newline_then_a_late_space_then_a_hard_cut() -> None:
    assert _cut_piece("abc", 5, False) == ("abc", "")
    assert _cut_piece("ab\ncd ef", 5, False) == ("ab", "cd ef")
    assert _cut_piece("ab\ncd\nef", 5, False) == ("ab\ncd", "ef")
    assert _cut_piece("ab cd\nef", 5, False) == ("ab cd", "ef")
    assert _cut_piece("abc def", 5, False) == ("abc", "def")
    assert _cut_piece("a bcdefghijkl", 10, False) == ("a bcdefghi", "jkl")
    assert _cut_piece("abcdefgh", 3, False) == ("abc", "defgh")


def test_cut_piece_in_reverse_mirrors_the_search() -> None:
    assert _cut_piece("ab\ncd ef", 5, True) == ("cd ef", "ab")
    assert _cut_piece("ab\ncd\nef", 5, True) == ("cd\nef", "ab")
    assert _cut_piece("abc def", 5, True) == ("def", "abc")
    assert _cut_piece("lkjihgfedcb a", 10, True) == ("ihgfedcb a", "lkj")
    assert _cut_piece("abcdefgh", 3, True) == ("fgh", "abcde")


def test_snake_patterns() -> None:
    assert _SNAKE1_PATTERN.sub(r"\1_\2", "getHTTPResponse") == "getHTTP_Response"
    assert _SNAKE2_PATTERN.sub(r"\1_\2", "getHTTP") == "get_HTTP"


def test_smart_split_part_reports_whether_a_part_is_kept() -> None:
    assert _smart_split_part(" x ", None, True, False, None) == (True, "x")
    assert _smart_split_part(" x ", None, False, False, None) == (True, " x ")
    assert _smart_split_part(" x y ", None, False, True, None) == (True, "xy")
    assert _smart_split_part("5", None, False, False, int) == (True, 5)
    assert _smart_split_part("5", lambda t: False, False, False, int) == (False, None)
    assert _smart_split_part(" 5 ", lambda t: t != "5", True, False, int) == (True, 5)
