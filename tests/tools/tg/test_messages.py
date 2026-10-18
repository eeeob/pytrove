from __future__ import annotations as _annotations

from pytrove.enums import TgMessageLength
from pytrove.tg_tools import split_tg_message


def test_split_tg_message_breaks_between_lines_and_cuts_long_ones() -> None:
    assert split_tg_message(" short ") == ["short"]
    # A line keeps its trailing newline while packing, so "aa\n" + "bb\n" is 6 characters.
    assert split_tg_message("aa\nbb\ncc", length=5) == ["aa", "bb\ncc"]
    assert split_tg_message("aa\nbb\ncc", length=5, reverse=True) == ["bb\ncc", "aa"]
    assert split_tg_message("abcdefgh", length=3) == ["abc", "def", "gh"]
    assert split_tg_message("abcdefgh\nx", length=3, reverse=True) == ["x", "gh", "def", "abc"]


def test_split_tg_message_keeps_text_of_exactly_the_limit_whole() -> None:
    assert split_tg_message("abc", length=3) == ["abc"]


def test_split_tg_message_defaults_to_telegrams_text_limit() -> None:
    text = "a" * TgMessageLength.TEXT

    assert split_tg_message(text) == [text]
    assert split_tg_message(text + "b") == [text, "b"]


def test_split_tg_message_drops_chunks_that_are_only_whitespace() -> None:
    # "   \n" is longer than the limit, so its blank "   " is cut off and then dropped.
    assert split_tg_message("aa\n   \nbb", length=3) == ["aa", "bb"]


def test_split_tg_message_in_reverse_fills_the_last_message() -> None:
    # Packed from the end, so the full message is the last lines and comes first.
    assert split_tg_message("a\nb\nc", length=4, reverse=True) == ["b\nc", "a"]
    assert split_tg_message("a\nb\nc", length=4) == ["a\nb", "c"]
