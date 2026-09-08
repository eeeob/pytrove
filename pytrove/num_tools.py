
from typing import Union, overload, Optional

from .typings import _True, _False, _T, Number, StrInt
from .validate_tools import validation
from .data_tools import map_deep

import ast
import operator
import logging
import random


log = logging.getLogger(__name__)
CALC_ALLOWED_CHARS = frozenset("0123456789*/-+.")

# Explicit allow-list of AST node/operator types for calc()'s expression
# evaluator. Anything else (function calls, attribute access, subscripts,
# names, Pow/**, etc.) raises instead of evaluating -- there is no eval()/
# exec() involved, so no code path can escape basic arithmetic on numbers.
_CALC_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_CALC_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval_calc_ast(node):
    if isinstance(node, ast.Expression):
        return _eval_calc_ast(node.body)

    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value

    if isinstance(node, ast.BinOp) and type(node.op) in _CALC_BINOPS:
        return _CALC_BINOPS[type(node.op)](_eval_calc_ast(node.left), _eval_calc_ast(node.right))

    if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_UNARYOPS:
        return _CALC_UNARYOPS[type(node.op)](_eval_calc_ast(node.operand))

    raise ValueError(f"Disallowed expression node: {type(node).__name__}")



@overload
def to_int(value: str, as_int: _True = ...) -> StrInt: ...
@overload
def to_int(value: str, as_int: _False) -> Union[StrInt, float]: ...
@overload
def to_int(value: _T, as_int: bool = ...) -> _T: ...
def to_int(value: Union[str, _T], as_int: bool = True):
    if not isinstance(value, str) or value.startswith("+"):
        return value
    
    try:
        return int(value) if (as_int or "." not in value) else float(value)
    except (ValueError, TypeError):
        return value


def to_int_deep(data: _T, as_int: bool = False) -> _T:
    """to_int, offered to every leaf under `data` instead of to one value
    -- and, for a mapping, to every key too, not only its values.

    map_deep(data, ...) with to_int itself as the function -- see it for
    what "every leaf, keys included, whatever the type" actually means and
    what it costs. Reach for map_deep directly for any other per-leaf
    transform; this is only to_int's own name kept for the one it's
    always meant.

    `as_int` is to_int's own: False (the default) lets a "3.5" become a
    float, True forces every convertible leaf to an int.
    """

    return map_deep(data, lambda value: to_int(value, as_int))


@overload
def calc(value: str, as_int: _False = ...) -> Union[StrInt, float]: ...
@overload
def calc(value: str, as_int: _True) -> StrInt: ...
@overload
def calc(value: _T, as_int: bool = ...) -> _T: ...
def calc(value: Union[str, _T], as_int: bool = False):
    if not isinstance(value, str):
        return value
    
    value = to_int(value, False)

    if isinstance(value, str):
        from .text_tools import clean_spaces
        c_value = clean_spaces(value)

        if all(i in CALC_ALLOWED_CHARS for i in c_value):
            try:
                c_value = _eval_calc_ast(ast.parse(c_value, mode="eval"))
            except Exception as e:
                log.exception(e)

        if isinstance(c_value, (int, float)):
            value = c_value
    
    if as_int and isinstance(value, float):
        value = int(value)

    return value


def apply_discount(price: Number, discount_percent: Number, ndigits: Optional[int] = 4) -> float:
    validation(discount_percent <= 100, "discount_percent must be <= 100")
    return round(price * (1 - discount_percent / 100), ndigits)

def reverse_discount(
    discounted_price: Number,
    discount_percent: Number,
    ndigits: Optional[int] = 4
) -> float:

    validation(
        0 <= discount_percent < 100,
        "discount_percent must be between 0 and < 100"
    )

    return round(discounted_price / (1 - discount_percent / 100), ndigits)

def jitter(
    base: Number,
    minus: Number = 2,
    plus: Number = 2
    ) -> float:
    
    low = max(0, base - minus)
    high = max(low, base + plus)

    return random.uniform(low, high)

__all__ = (
    "to_int",
    "to_int_deep",
    "calc", "reverse_discount",
    "apply_discount", "jitter",

)