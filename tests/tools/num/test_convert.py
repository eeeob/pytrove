from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

from pytrove.num_tools import calc, to_int, to_int_deep, CALC_ALLOWED_CHARS

if TYPE_CHECKING:
    import pytest


def test_to_int_basic() -> None:
    assert to_int("5") == 5
    assert to_int("5.5", as_int=False) == 5.5
    assert to_int("notanumber") == "notanumber"
    assert to_int("+123") == "+123"  # leading '+' is treated as non-numeric passthrough


def test_to_int_keeps_a_plus_prefixed_string() -> None:
    assert to_int("+966") == "+966"


def test_to_int_reads_a_decimal_as_float_only_when_asked() -> None:
    assert to_int("3.5", False) == 3.5
    assert to_int("3.5") == "3.5"
    assert to_int("7", False) == 7
    assert to_int(None) is None


def test_to_int_deep_converts_every_leaf() -> None:
    data = {"id": "123", "tags": ["1", "2.5", "x"], "meta": {"count": "10"}}
    assert to_int_deep(data) == {"id": 123, "tags": [1, 2.5, "x"], "meta": {"count": 10}}


def test_to_int_deep_converts_keys_too() -> None:
    assert to_int_deep({"1": "a", "2": "b"}) == {1: "a", 2: "b"}


def test_to_int_deep_walks_a_set() -> None:
    assert to_int_deep({"1", "2"}) == {1, 2}


def test_to_int_deep_preserves_container_type() -> None:
    result = to_int_deep(("1", "2", ["3"]))
    assert type(result) is tuple
    assert result == (1, 2, [3])


def test_to_int_deep_threads_as_int_to_every_leaf() -> None:
    # as_int=True is to_int's own -- a value with a "." only converts when
    # int() itself accepts it outright, same as to_int("3.0", as_int=True).
    assert to_int_deep(["3", "3.0"], as_int=True) == [3, "3.0"]
    assert to_int_deep(["3", "3.0"], as_int=False) == [3, 3.0]


def test_to_int_deep_leaves_a_plain_leaf_untouched() -> None:
    assert to_int_deep("notanumber") == "notanumber"
    assert to_int_deep(None) is None


def test_calc_basic_arithmetic() -> None:
    assert calc("2+2") == 4
    assert calc("10/2") == 5.0
    assert calc("2*3-1") == 5
    assert calc("-5+2") == -3
    assert calc("not math") == "not math"


def test_calc_reads_a_plain_number_without_evaluating() -> None:
    assert calc("5") == 5
    assert calc("2.5") == 2.5
    assert calc("2.5", as_int=True) == 2
    assert calc("+966") == 966  # a leading `+` is unary plus here, unlike in `to_int`


def test_calc_long_compound_expressions_respect_operator_precedence() -> None:
    # calc()'s AST-based evaluator must match standard +-*/ precedence exactly,
    # the same as the eval() it replaced -- verified here against Python's own
    # operator precedence as ground truth.
    assert calc("2+3*4-5/2+10*3-7+1*2-3/3+4-5*6+7-8*9+10") == -45.5
    assert calc("1+2+3+4+5+6+7+8+9+10-1-2-3-4-5") == 40
    assert calc("2*3*4*5*6") == 720
    assert calc("-3.5+2*4-10/5+1.25*4") == 7.5
    assert calc("100-50+25-12.5+6.25-3.125") == 65.625
    assert calc("1*2*3*4*5*6*7*8*9*10") == 3628800


def test_calc_rejects_power_operator_dos_vector() -> None:
    # calc() must never evaluate "**" -- chained exponentiation like this can
    # exhaust memory/CPU. It should fail safe and return the original string.
    assert calc("9**9**9") == "9**9**9"


def test_calc_division_by_zero_falls_back_to_original_string() -> None:
    assert calc("1/0") == "1/0"


def test_calc_no_eval_side_channel() -> None:
    # Regression: calc() must never execute arbitrary code, even indirectly.
    assert calc("__import__('os')") == "__import__('os')"


def test_calc_truncates_to_int_when_asked() -> None:
    assert calc("7/2") == 3.5
    assert calc("7/2", as_int=True) == 3
    assert calc(5) == 5


def test_calc_logs_and_keeps_the_text_when_evaluation_fails(caplog: pytest.LogCaptureFixture) -> None:
    assert calc("1/0") == "1/0"
    assert "Failed to evaluate" in caplog.text


def test_calc_allowed_chars_are_digits_operators_and_the_point() -> None:
    assert frozenset("0123456789*/-+.") == CALC_ALLOWED_CHARS
