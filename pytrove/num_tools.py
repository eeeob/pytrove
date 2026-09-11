
from typing import Union, overload, Optional

from .typings import _True, _False, _T, Number, StrInt
from .validate_tools import validation
from .data_tools import map_deep

import ast
import operator
import logging
import random

from math import sqrt


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

def reverse_discount(discounted_price: Number, discount_percent: Number, ndigits: Optional[int] = 4) -> float:
    validation(0 <= discount_percent < 100, "discount_percent must be between 0 and < 100")
    return round(discounted_price / (1 - discount_percent / 100), ndigits)

def _tri_cdf(x: float, low: float, high: float, mode: float) -> float:
    """Triangular CDF at `x` -- P(X <= x) for X ~ Triangular(low, high, mode).

    Both `mode == low` and `mode == high` are safe: the branch whose
    denominator would be zero is exactly the branch no `x` in `(low, high)`
    can reach.
    """

    if x <= low:
        return 0.0

    if x >= high:
        return 1.0

    span = high - low

    if x <= mode:
        return (x - low) * (x - low) / (span * (mode - low))

    return 1.0 - (high - x) * (high - x) / (span * (high - mode))


def _tri_icdf(u: float, low: float, high: float, mode: float) -> float:
    """Triangular quantile -- the `x` with `_tri_cdf(x) == u`.

    A plain uniform draw in `u` gives a triangular sample; a draw confined
    to `[_tri_cdf(a), _tri_cdf(b)]` gives one truncated to `[a, b]` with no
    draw-and-retry -- the trick behind jitter()'s anti-bunching.
    """

    span = high - low

    if span <= 0.0:
        return low

    peak = (mode - low) / span

    if u <= peak:
        return low + sqrt(u * span * (mode - low))

    return high - sqrt((1.0 - u) * span * (high - mode))


def jitter(
    value: float,
    decrease: float,
    increase: float,
    bias: float = 0.5,
    previous: Optional[float] = None,
    min_distance: float = 0.0,
    *,
    rng: Optional[random.Random] = None,
) -> float:
    """A random value near `value`, `decrease`/`increase` giving how far
    below/above it may land as fractions of it (``0.1`` == 10%), `bias`
    tilting the draw toward one end, and `previous`/`min_distance` keeping a
    run of draws from bunching up.

    The window is ``[value*(1 - decrease), value*(1 + increase)]`` (its ends
    put back in order first, so a negative `value` still works). The shape
    across it is triangular, peaking `bias` of the way from the low end to
    the high one -- ``0.5`` (default) is a symmetric peak in the middle,
    ``1.0`` pushes the mass against the high end (favouring the full
    `increase`), ``0.0`` against the low end; anything outside ``[0, 1]`` is
    clamped.

    `previous` (the last value handed out) together with `min_distance` (an
    absolute gap, same units as `value`) cut a hole ``previous +/-
    min_distance`` out of the window and the draw comes from what is left --
    taken straight from the truncated triangular by inverse transform, never
    by drawing until one lands clear, so a tight window costs no more than a
    loose one. If the hole covers the whole window (`min_distance` too large
    for it) the reachable end furthest from `previous` is returned -- the
    best separation still on offer.

    Note what this does *not* do: called in a loop **without** `previous`
    it is 50 independent triangular draws, and independent draws from a
    peaked shape land near the peak again and again -- that clustering is
    the distribution, not a bug. Passing `previous` yourself only forbids a
    single band around it, which tends to leave draws hugging the edge of
    that band. For a *sequence* that actually spreads, use Jitter -- it
    walks the window with a low-discrepancy step so consecutive values stay
    far apart by construction.

    Pass `rng` (any ``random.Random``) for a reproducible stream; the module
    `random` is used otherwise.
    """

    src = rng or random

    low = value * (1.0 - decrease)
    high = value * (1.0 + increase)

    if low > high:
        low, high = high, low

    if high <= low:
        return low

    if bias < 0.0:
        bias = 0.0
    elif bias > 1.0:
        bias = 1.0

    mode = low + (high - low) * bias

    if previous is None or min_distance <= 0.0:
        return _tri_icdf(src.random(), low, high, mode)

    cut_low = previous - min_distance
    cut_high = previous + min_distance

    if cut_low < low:
        cut_low = low
    if cut_high > high:
        cut_high = high

    if cut_low >= cut_high:                      # the hole misses the window
        return _tri_icdf(src.random(), low, high, mode)

    left = (low, cut_low) if cut_low > low else None
    right = (cut_high, high) if cut_high < high else None

    if left is None and right is None:          # the hole covers the window
        return low if (previous - low) >= (high - previous) else high

    if left is None:
        seg = right
    elif right is None:
        seg = left
    else:
        mass_left = _tri_cdf(left[1], low, high, mode) - _tri_cdf(left[0], low, high, mode)
        mass_right = _tri_cdf(right[1], low, high, mode) - _tri_cdf(right[0], low, high, mode)
        total = mass_left + mass_right

        if total > 0.0:
            seg = left if src.random() * total < mass_left else right
        else:                                   # both tails carry ~no mass
            span_left = left[1] - left[0]
            span_total = span_left + (right[1] - right[0])

            if span_total <= 0.0:
                return low

            seg = left if src.random() * span_total < span_left else right

    a, b = seg
    u_low = _tri_cdf(a, low, high, mode)
    u_high = _tri_cdf(b, low, high, mode)

    if u_high <= u_low:
        return (a + b) * 0.5

    return _tri_icdf(src.uniform(u_low, u_high), low, high, mode)


__all__ = (
    "to_int",
    "to_int_deep",
    "calc", "reverse_discount",
    "apply_discount", "jitter",

)