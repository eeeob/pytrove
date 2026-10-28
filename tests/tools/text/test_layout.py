from __future__ import annotations as _annotations

import random
import sys

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


@pytest.mark.parametrize("limit", [0, -1])
def test_chunk_text_rejects_a_limit_below_one(limit: int) -> None:
    with pytest.raises(ValueError, match="max_length"):
        chunk_text("abc", limit)


@pytest.mark.parametrize(
    ("text", "limit", "forward", "backward"),
    [
        ("para one\n\npara two", 8, ["para one", "para two"], ["para two", "para one"]),
        ("hello  world", 5, ["hello", "world"], ["world", "hello"]),
        ("abc\n\ndef", 3, ["abc", "def"], ["def", "abc"]),
        ("world  hello", 5, ["world", "hello"], ["hello", "world"]),
        ("ab \n cd", 2, ["ab", "cd"], ["cd", "ab"]),
    ],
)
def test_chunk_text_skips_the_whitespace_left_at_a_cut(
    text: str, limit: int, forward: list[str], backward: list[str]
) -> None:
    assert chunk_text(text, limit) == forward
    assert chunk_text(text, limit, reverse=True) == backward


def test_chunk_text_breaks_only_at_newline_and_space() -> None:
    # `\r\n` works, since the `\r` is stripped with the piece.
    assert chunk_text("aaa\r\nbbb", 4) == ["aaa", "bbb"]
    assert chunk_text("aaa\r\nbbb", 4, reverse=True) == ["bbb", "aaa"]
    # A lone `\r`, `\t` or `\v` is no break, so the cut is hard.
    for char in "\r\t\v":
        assert chunk_text(f"a{char}bcd", 3) == [f"a{char}b", "cd"]


def test_chunk_text_in_reverse_uses_a_break_just_past_the_limit() -> None:
    assert chunk_text("aaa bbb", 3, reverse=True) == ["bbb", "aaa"]


def test_chunk_text_in_reverse_drops_blank_pieces() -> None:
    assert chunk_text("abc\n\n\n   \ndef", 4, reverse=True) == ["def", "abc"]


def test_chunk_text_defaults_to_the_telegram_limit() -> None:
    text = "word " * 1000

    assert chunk_text(text) == [" ".join(["word"] * 819), " ".join(["word"] * 181)]


@pytest.mark.parametrize("reverse", [False, True])
def test_chunk_text_never_cuts_a_word_when_a_break_fits(reverse: bool) -> None:
    # Each word is longer than `limit // 10`, so the break after the first word
    # of a window always qualifies and no piece should end mid-word.
    rng = random.Random(1)

    for _ in range(2000):
        limit = rng.randint(1, 30)
        words = ["x" * rng.randint(limit // 10 + 1, limit) for _ in range(rng.randint(0, 12))]
        gaps = [rng.choice([" ", "  ", "\n", "\n\n", " \n "]) for _ in words]
        text = "".join(word + gap for word, gap in zip(words, gaps, strict=True))
        pieces = chunk_text(text, limit, reverse=reverse)
        ordered = pieces[::-1] if reverse else pieces

        assert all(len(p) <= limit for p in pieces)
        assert [word for piece in ordered for word in piece.split()] == words


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


def test_format_exc_tree_terminates_on_a_self_cycle() -> None:
    error = ValueError("a")
    error.__context__ = error

    assert format_exc_tree(error) == "└─ ValueError: a"


def test_format_exc_tree_renders_a_single_exception_and_an_empty_message() -> None:
    assert format_exc_tree(ValueError("v")) == "└─ ValueError: v"
    assert format_exc_tree(ValueError()) == "└─ ValueError: "


def test_format_exc_tree_nests_every_level() -> None:
    first = RuntimeError("1")
    second = ValueError("2")
    first.__cause__ = second
    second.__context__ = KeyError("3")

    assert format_exc_tree(first) == (
        "└─ RuntimeError: 1\n    └─ ValueError: 2\n        └─ KeyError: '3'"
    )


def test_format_exc_tree_hides_a_context_suppressed_by_from_none() -> None:
    try:
        try:
            missing = "k"
            raise KeyError(missing)
        except KeyError:
            msg = "v"
            raise ValueError(msg) from None
    except ValueError as error:
        assert format_exc_tree(error) == "└─ ValueError: v"


def test_format_exc_tree_aligns_a_multi_line_message() -> None:
    error = ValueError("line1\nline2")
    error.__cause__ = KeyError("k")

    assert format_exc_tree(error) == "└─ ValueError: line1\n   line2\n    └─ KeyError: 'k'"


def test_format_exc_tree_lists_exception_group_members() -> None:
    if sys.version_info < (3, 11):
        pytest.skip("exception groups are new in 3.11")

    inner = ValueError("a")
    inner.__cause__ = OSError("disk")
    group = ExceptionGroup("g", [inner, TypeError("b")])  # noqa: F821 - a 3.11 builtin, guarded above

    assert format_exc_tree(group) == (
        "└─ ExceptionGroup: g (2 sub-exceptions)\n"
        "    ├─ ValueError: a\n"
        "        └─ OSError: disk\n"
        "    ├─ TypeError: b"
    )


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


def test_numbering_empty_input() -> None:
    assert numbering([]) == ""
    assert numbering([], line_sep=None) == []
    assert numbering({}) == ""


def test_numbering_takes_any_container_and_a_string_as_one_value() -> None:
    assert numbering(("a", "b")) == "1. a\n2. b"
    assert numbering({"a"}) == "1. a"
    assert numbering(v for v in "ab") == "1. a\n2. b"
    assert numbering("abc") == "1. abc"
    assert numbering("") == "1. "


def test_numbering_negative_start() -> None:
    assert numbering(["a", "b"], -1) == "-1. a\n0. b"


def test_numbering_line_sep_none_positionally() -> None:
    assert numbering(["a"], 1, None, None) == ["1. a"]
    assert numbering({"a": 1}, 1, None, None) == ["1. a - 1"]
