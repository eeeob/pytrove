"""Helpers private to `num_tools`: the arithmetic evaluator behind `calc`."""

from __future__ import annotations as _annotations

import ast
import operator
from collections.abc import Callable
from typing import Any, Final

_CALC_BINOPS: Final[dict[type[ast.operator], Callable[[Any, Any], Any]]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
"""The binary operators `calc` evaluates. Anything else, `**` included, is refused."""

_CALC_UNARYOPS: Final[dict[type[ast.unaryop], Callable[[Any], Any]]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
"""The unary operators `calc` evaluates."""


def _eval_calc_ast(node: ast.AST) -> int | float:
    """Evaluate an arithmetic expression tree from an allow-list, with no `eval`.

    Only number constants and the operators in `_CALC_BINOPS` and
    `_CALC_UNARYOPS` are evaluated, so no input can reach anything else.

    Args:
        node: The tree, usually from `ast.parse(text, mode="eval")`.

    Returns:
        The expression's value.

    Raises:
        ValueError: If the tree holds any other kind of node.
        ZeroDivisionError: If it divides by zero.
    """
    if isinstance(node, ast.Expression):
        return _eval_calc_ast(node.body)

    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value

    if isinstance(node, ast.BinOp) and type(node.op) in _CALC_BINOPS:
        return _CALC_BINOPS[type(node.op)](_eval_calc_ast(node.left), _eval_calc_ast(node.right))

    if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_UNARYOPS:
        return _CALC_UNARYOPS[type(node.op)](_eval_calc_ast(node.operand))

    msg = f"Disallowed expression node: {type(node).__name__}"
    raise ValueError(msg)


__all__ = (
    "_eval_calc_ast",
    "_CALC_BINOPS",
    "_CALC_UNARYOPS",
)
