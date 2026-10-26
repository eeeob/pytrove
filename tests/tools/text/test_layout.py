from __future__ import annotations as _annotations

import random

import pytest

from pytrove.enums import TgMessageLength
from pytrove.text_tools import chunk_text, format_exc_tree, numbering


def test_chunk_text_under_limit_returns_single_chunk() -> None:
    assert chunk_text("short text", max_length=100) == ["short text"]
    assert chunk_text("x" * TgMessageLength.TEXT) == ["x" * TgMessageLength.TEXT]


def test_chunk_text_strips_the_whole_text_first() -> None:
    assert chunk_text(" short ") == ["short"]
    assert chunk_text("  hi  ", 10) == ["hi"]
    # Without its surrounding spaces the text fits, so it stays one piece.
    assert chunk_text("  a b  ", 3) == ["a b"]


def test_chunk_text_returns_no_pieces_for_blank_text() -> None:
    assert chunk_text("   ") == []
    assert chunk_text("") == []


def test_chunk_text_splits_on_newline_when_possible() -> None:
    text = ("a" * 50 + "\n") + ("b" * 50)
    chunks = chunk_text(text, max_length=60)
    assert chunks == ["a" * 50, "b" * 50]


def test_chunk_text_hard_splits_when_no_separator_available() -> None:
    text = "a" * 250
    chunks = chunk_text(text, max_length=100)
    assert len(chunks) == 3
    assert "".join(chunks) == text


def test_chunk_text_breaks_at_a_late_space_but_not_an_early_one() -> None:
    assert chunk_text("aaaa bbbb", max_length=6) == ["aaaa", "bbbb"]
    assert chunk_text("a bbbbbbbbbbbbbbbbbbbbbbbbbbb", max_length=20) == [
        "a bbbbbbbbbbbbbbbbbb",
        "bbbbbbbbb",
    ]


def test_chunk_text_drops_blank_pieces() -> None:
    assert chunk_text("abc\n\n\n   \ndef", max_length=4) == ["abc", "def"]


def test_chunk_text_uses_a_break_just_past_the_limit() -> None:
    assert chunk_text("aa\nbb\ncc", 5) == ["aa\nbb", "cc"]
    assert chunk_text("aaa bbb", 3) == ["aaa", "bbb"]
    assert chunk_text("hello world foo", 10) == ["hello", "world foo"]


def test_chunk_text_in_reverse_cuts_from_the_end() -> None:
    assert chunk_text("aa\nbb\ncc", 5, reverse=True) == ["bb\ncc", "aa"]
    assert chunk_text("foo world hello", 10, reverse=True) == ["hello", "foo world"]
    assert chunk_text("abcdefgh", 3, reverse=True) == ["fgh", "cde", "ab"]
    assert chunk_text("short", 10, reverse=True) == ["short"]


def test_chunk_text_rejects_a_limit_below_one() -> None:
    with pytest.raises(ValueError, match="max_length"):
        chunk_text("abc", 0)


@pytest.mark.parametrize("reverse", [False, True])
def test_chunk_text_pieces_fit_and_keep_every_non_space_character(reverse: bool) -> None:
    rng = random.Random(0)

    for _ in range(2000):
        text = "".join(rng.choice("ab \n") for _ in range(rng.randint(0, 30)))
        limit = rng.randint(1, 8)
        pieces = chunk_text(text, limit, reverse=reverse)
        ordered = pieces[::-1] if reverse else pieces

        assert all(len(p) <= limit for p in pieces)
        assert "".join("".join(ordered).split()) == "".join(text.split())


def test_format_exc_tree_shows_cause_chain() -> None:
    outer = RuntimeError("outer")
    outer.__cause__ = ValueError("inner")
    outer.__context__ = KeyError("ignored while there is a cause")

    assert format_exc_tree(outer) == "└─ RuntimeError: outer\n    └─ ValueError: inner"


def test_format_exc_tree_follows_the_context_without_a_cause() -> None:
    error = ValueError("v")
    error.__context__ = KeyError("k")

    assert format_exc_tree(error) == "└─ ValueError: v\n    └─ KeyError: 'k'"


def test_format_exc_tree_terminates_on_a_context_cycle() -> None:
    a = ValueError("a")
    b = KeyError("b")
    a.__context__ = b
    b.__context__ = a

    assert format_exc_tree(a).count("└─") == 2


def test_numbering_list_default_format() -> None:
    assert numbering(["a", "b", "c"]) == "1. a\n2. b\n3. c"


def test_numbering_dict_default_format() -> None:
    assert numbering({"x": 1, "y": 2}) == "1. x - 1\n2. y - 2"


def test_numbering_custom_start_and_parser() -> None:
    assert numbering(["a", "b"], start=5, line_parser=lambda v, c: f"[{c}] {v}") == "[5] a\n[6] b"


def test_numbering_line_sep_none_returns_list() -> None:
    assert numbering(["a", "b"], line_sep=None) == ["1. a", "2. b"]
    assert numbering(["a", "b"], line_sep=" | ") == "1. a | 2. b"


def test_numbering_a_mapping_with_a_custom_parser() -> None:
    assert numbering({"a": 1}, start=3, line_parser=lambda k, v, n: f"{n}:{k}={v}") == "3:a=1"
    assert numbering({"a": 1, "b": 2}, line_sep=None) == ["1. a - 1", "2. b - 2"]
