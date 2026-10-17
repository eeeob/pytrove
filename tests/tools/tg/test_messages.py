from __future__ import annotations as _annotations

from pytrove.tg_tools import split_tg_message


def test_split_tg_message_breaks_between_lines_and_cuts_long_ones() -> None:
    assert split_tg_message(" short ") == ["short"]
    # A line keeps its trailing newline while packing, so "aa\n" + "bb\n" is 6 characters.
    assert split_tg_message("aa\nbb\ncc", length=5) == ["aa", "bb\ncc"]
    assert split_tg_message("aa\nbb\ncc", length=5, reverse=True) == ["bb\ncc", "aa"]
    assert split_tg_message("abcdefgh", length=3) == ["abc", "def", "gh"]
    assert split_tg_message("abcdefgh\nx", length=3, reverse=True) == ["x", "gh", "def", "abc"]
