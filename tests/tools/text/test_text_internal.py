from __future__ import annotations as _annotations

import sys

import pytest

from pytrove.text_tools._internal import (
    _cut_piece,
    _exc_tree_lines,
    _SNAKE1_PATTERN,
    _SNAKE2_PATTERN,
    _SPACES_PATTERN,
    _WHITESPACE_PATTERN,
)


@pytest.mark.parametrize(
    ("text", "max_length", "cut"),
    [
        ("abc", 5, 3),
        ("ab\ncd ef", 5, 2),
        ("ab\ncd\nef", 5, 5),
        ("ab cd\nef", 5, 5),
        ("abc def", 5, 3),
        # The space must leave more than `max_length // 10` characters: 1 is rejected, 2 accepted.
        ("a bcdefghijkl", 10, 10),
        ("ab cdefghijk", 10, 2),
        ("abcdefgh", 3, 3),
        # A newline at the window start leaves nothing, so the space search takes over.
        ("\nabc def", 5, 4),
        # A space at the window start is no break either.
        (" abcdefgh", 5, 5),
        # The break just past the limit.
        ("aaa bbb", 3, 3),
        ("ab", 1, 1),
        ("a b", 1, 1),
    ],
)
def test_cut_piece_forward(text: str, max_length: int, cut: int) -> None:
    assert _cut_piece(text, 0, len(text), max_length, False) == cut


@pytest.mark.parametrize(
    ("text", "max_length", "cut"),
    [
        ("abc", 5, 0),
        ("ab\ncd ef", 5, 3),
        ("ab\ncd\nef", 5, 3),
        ("abc def", 5, 4),
        ("lkjihgfedcb a", 10, 3),
        ("kjihgfedc ba", 10, 10),
        ("abcdefgh", 3, 5),
        # A newline at the window end leaves nothing, so the space search takes over.
        ("abc def\n", 5, 4),
        # The break at window index 0, just past the limit.
        ("aaa bbb", 3, 4),
        ("ba", 1, 1),
        ("a b", 1, 2),
    ],
)
def test_cut_piece_in_reverse(text: str, max_length: int, cut: int) -> None:
    assert _cut_piece(text, 0, len(text), max_length, True) == cut


def test_cut_piece_searches_only_between_the_offsets() -> None:
    assert _cut_piece("xx abc def", 3, 10, 5, False) == 6
    assert _cut_piece("abc def yy", 0, 7, 5, True) == 4
    # The space before `start` / after `end` is outside the window.
    assert _cut_piece("a bcdefgh", 2, 9, 5, False) == 7
    assert _cut_piece("abcdefg h", 0, 7, 5, True) == 2
    assert _cut_piece("xxabc", 2, 5, 5, False) == 5
    assert _cut_piece("abcxx", 0, 3, 5, True) == 0


def test_exc_tree_lines_follows_the_chain_from_a_level() -> None:
    error = ValueError("v")
    error.__cause__ = KeyError("k")

    assert list(_exc_tree_lines(error, 1, set())) == [
        "    └─ ValueError: v",
        "        └─ KeyError: 'k'",
    ]
    assert list(_exc_tree_lines(None, 0, set())) == []


def test_exc_tree_lines_skips_what_was_already_seen() -> None:
    error = ValueError("v")
    cause = KeyError("k")
    error.__cause__ = cause

    assert list(_exc_tree_lines(error, 0, {id(cause)})) == ["└─ ValueError: v"]


def test_exc_tree_lines_honours_suppress_context() -> None:
    error = ValueError("v")
    error.__context__ = KeyError("k")
    error.__suppress_context__ = True

    assert list(_exc_tree_lines(error, 0, set())) == ["└─ ValueError: v"]


def test_exc_tree_lines_aligns_a_multi_line_message() -> None:
    assert list(_exc_tree_lines(ValueError("a\nb"), 1, set())) == ["    └─ ValueError: a\n       b"]


def test_exc_tree_lines_lists_group_members_before_the_cause() -> None:
    if sys.version_info < (3, 11):
        pytest.skip("exception groups are new in 3.11")

    group = ExceptionGroup("g", [ValueError("a")])  # noqa: F821 - a 3.11 builtin, guarded above
    group.__cause__ = KeyError("c")

    assert list(_exc_tree_lines(group, 0, set())) == [
        "└─ ExceptionGroup: g (1 sub-exception)",
        "    ├─ ValueError: a",
        "    └─ KeyError: 'c'",
    ]


def test_snake_patterns() -> None:
    assert _SNAKE1_PATTERN.sub(r"\1_\2", "getHTTPResponse") == "getHTTP_Response"
    assert _SNAKE1_PATTERN.sub(r"\1_\2", "my_Var") == "my_Var"
    assert _SNAKE2_PATTERN.sub(r"\1_\2", "getHTTP") == "get_HTTP"


def test_spaces_pattern_matches_whitespace_runs_but_keeps_newlines() -> None:
    assert _SPACES_PATTERN.sub("", " a \t\r\n b\u00a0c\u2003") == "a\nbc"


def test_whitespace_pattern_matches_every_whitespace_run() -> None:
    assert _WHITESPACE_PATTERN.sub("", " a \t\r\n b\u00a0c\u2003") == "abc"
