from __future__ import annotations as _annotations

import ast
import operator

import pytest

from pytrove.num_tools._internal import _eval_calc_ast, _CALC_BINOPS, _CALC_UNARYOPS


@pytest.mark.parametrize(
    ("text", "expected"), [("1+2*3", 7), ("-4", -4), ("+4", 4), ("6/4", 1.5), ("2-3", -1)]
)
def test_eval_calc_ast_evaluates_allowed_arithmetic(text: str, expected: float) -> None:
    assert _eval_calc_ast(ast.parse(text, mode="eval")) == expected


@pytest.mark.parametrize("text", ["2**3", "abs(1)", "a", "True", "'x'", "(1,2)"])
def test_eval_calc_ast_refuses_everything_else(text: str) -> None:
    with pytest.raises(ValueError, match="Disallowed expression node"):
        _eval_calc_ast(ast.parse(text, mode="eval"))


def test_eval_calc_ast_raises_on_a_division_by_zero() -> None:
    with pytest.raises(ZeroDivisionError):
        _eval_calc_ast(ast.parse("1/0", mode="eval"))


def test_operator_tables() -> None:
    assert _CALC_BINOPS == {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
    }
    assert _CALC_UNARYOPS == {ast.UAdd: operator.pos, ast.USub: operator.neg}
