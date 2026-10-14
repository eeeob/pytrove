from __future__ import annotations as _annotations

import ast
import operator
import random

import pytest

from pytrove.errors import ValidationError
from pytrove.num_tools import apply_discount, calc, jitter, reverse_discount, to_int, CALC_ALLOWED_CHARS
from pytrove.num_tools._internal import _eval_calc_ast, _CALC_BINOPS, _CALC_UNARYOPS


def test_to_int_keeps_a_plus_prefixed_string() -> None:
    assert to_int("+966") == "+966"


def test_to_int_reads_a_decimal_as_float_only_when_asked() -> None:
    assert to_int("3.5", False) == 3.5
    assert to_int("3.5") == "3.5"
    assert to_int("7", False) == 7
    assert to_int(None) is None


def test_calc_truncates_to_int_when_asked() -> None:
    assert calc("7/2") == 3.5
    assert calc("7/2", as_int=True) == 3
    assert calc(5) == 5


def test_calc_logs_and_keeps_the_text_when_evaluation_fails(caplog: pytest.LogCaptureFixture) -> None:
    assert calc("1/0") == "1/0"
    assert "Failed to evaluate" in caplog.text


def test_calc_allowed_chars_are_digits_operators_and_the_point() -> None:
    assert frozenset("0123456789*/-+.") == CALC_ALLOWED_CHARS


@pytest.mark.parametrize(("text", "expected"), [("1+2*3", 7), ("-4", -4), ("+4", 4), ("6/4", 1.5), ("2-3", -1)])
def test_eval_calc_ast_evaluates_allowed_arithmetic(text: str, expected: float) -> None:
    assert _eval_calc_ast(ast.parse(text, mode="eval")) == expected


@pytest.mark.parametrize("text", ["2**3", "abs(1)", "a", "True", "'x'", "(1,2)"])
def test_eval_calc_ast_refuses_everything_else(text: str) -> None:
    with pytest.raises(ValueError, match="Disallowed expression node"):
        _eval_calc_ast(ast.parse(text, mode="eval"))


def test_operator_tables() -> None:
    assert _CALC_BINOPS == {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
    assert _CALC_UNARYOPS == {ast.UAdd: operator.pos, ast.USub: operator.neg}


def test_discount_bounds_are_validated() -> None:
    with pytest.raises(ValidationError):
        apply_discount(100, 101)

    with pytest.raises(ValidationError):
        reverse_discount(100, 100)

    with pytest.raises(ValidationError):
        reverse_discount(100, -1)


def test_discount_rounding() -> None:
    assert apply_discount(10, 33.333, ndigits=2) == 6.67
    assert reverse_discount(80, 20) == 100.0


def test_jitter_clamps_an_out_of_range_bias() -> None:
    rng = random.Random(1)
    low = [jitter(100, 0.1, 0.1, bias=-5, rng=rng) for _ in range(200)]
    high = [jitter(100, 0.1, 0.1, bias=5, rng=rng) for _ in range(200)]
    assert all(90 <= v <= 110 for v in low + high)
    assert sum(low) < sum(high)
