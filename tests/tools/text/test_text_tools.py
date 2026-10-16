from pytrove import (
    chunk_text, numbering, smart_split, format_exc_tree,
    y_or_n, en_or_dis, op_or_cl,
)
from pytrove import clean_spaces, to_str, split_part


def test_chunk_text_under_limit_returns_single_chunk():
    assert chunk_text("short text", max_length=100) == ["short text"]


def test_chunk_text_splits_on_newline_when_possible():
    text = ("a" * 50 + "\n") + ("b" * 50)
    chunks = chunk_text(text, max_length=60)
    assert len(chunks) >= 2
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_chunk_text_hard_splits_when_no_separator_available():
    text = "a" * 250
    chunks = chunk_text(text, max_length=100)
    assert len(chunks) == 3
    assert "".join(chunks) == text


def test_numbering_list_default_format():
    result = numbering(["a", "b", "c"])
    assert result == "1. a\n2. b\n3. c"


def test_numbering_dict_default_format():
    result = numbering({"x": 1, "y": 2})
    assert result == "1. x - 1\n2. y - 2"


def test_numbering_custom_start_and_parser():
    result = numbering(["a", "b"], start=5, line_parser=lambda v, c: f"[{c}] {v}")
    assert result == "[5] a\n[6] b"


def test_numbering_line_sep_none_returns_list():
    result = numbering(["a", "b"], line_sep=None)
    assert result == ["1. a", "2. b"]


def test_smart_split_basic():
    assert smart_split("a,b,c", separator=",") == ["a", "b", "c"]


def test_smart_split_calls_a_callable_separator():
    assert smart_split("a;b", separator=lambda: ";") == ["a", "b"]


def test_smart_split_none_separator_splits_on_whitespace_like_str_split():
    assert smart_split("a b  c", separator=None) == ["a", "b", "c"]


def test_smart_split_indexing_int_returns_single_item():
    assert smart_split("a,b,c", 1, separator=",") == "b"


def test_smart_split_indexing_slice_returns_list():
    assert smart_split("a,b,c,d", slice(1, 3), separator=",") == ["b", "c"]


def test_smart_split_strip_and_remove_spaces():
    assert smart_split(" a , b ", separator=",", strip=True) == ["a", "b"]
    assert smart_split(" a b , c d ", separator=",", remove_spaces=True) == ["ab", "cd"]


def test_format_exc_tree_shows_cause_chain():
    try:
        try:
            raise ValueError("inner")
        except ValueError as e:
            raise RuntimeError("outer") from e
    except RuntimeError as exc:
        tree = format_exc_tree(exc)

    assert "RuntimeError: outer" in tree
    assert "ValueError: inner" in tree
    # outer error must appear before (shallower than) the inner cause
    assert tree.index("RuntimeError") < tree.index("ValueError")


def test_y_or_n():
    assert y_or_n(True) == "✅"
    assert y_or_n(False) == "❌"
    assert y_or_n(1) == "✅"
    assert y_or_n(0) == "❌"


def test_en_or_dis_and_op_or_cl():
    assert en_or_dis(True) == "مفعل ✅"
    assert en_or_dis(False) == "معطل ❌"
    assert op_or_cl(True) == "مفتوح ✅"
    assert op_or_cl(False) == "مغلق ❌"


def test_format_exc_tree_terminates_on_a_context_cycle():
    a = ValueError("a")
    b = KeyError("b")
    a.__context__ = b
    b.__context__ = a

    assert format_exc_tree(a).count("└─") == 2


def test_clean_spaces():
    assert clean_spaces("a b\nc") == "abc"
    assert clean_spaces("a b\nc", with_lines=False) == "ab\nc"


def test_to_str():
    assert to_str(5) == "5"
    assert to_str(None) is None
    assert to_str([1, 2]) == [1, 2]


def test_split_part():
    assert split_part("a,b,c", ",", 1) == "b"
    assert split_part("a,b", ",", 5) == "a,b"  # out-of-range index falls back to original
