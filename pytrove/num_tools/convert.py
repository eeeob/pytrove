"""Reading numbers out of strings, and evaluating simple arithmetic."""

from __future__ import annotations as _annotations

import ast
import logging
import math
from typing import TYPE_CHECKING, Any, overload

from ..constants import CALC_EXPRESSION_CHARS
from ..data_tools import map_deep
from ..text_tools import clean_spaces
from ._internal import _eval_calc_ast

if TYPE_CHECKING:
    from ..typings import NestedContainer, StrInt, _False, _T, _True

log = logging.getLogger(__name__)


@overload
def to_int(value: str, as_int: _True = True) -> StrInt: ...
@overload
def to_int(value: str, as_int: _False) -> StrInt | float: ...
@overload
def to_int(value: str, as_int: bool) -> StrInt | float: ...
@overload
def to_int(value: _T, as_int: bool = True) -> _T: ...
def to_int(value: Any, as_int: bool = True) -> Any:
    """Turn a numeric string into a number, leaving everything else as it is.

    A string starting with `+` is kept as text, since it is usually a phone number.

    Args:
        value: The value to convert.
        as_int: Whether only integer strings convert, a decimal string being
            returned as text; `False` also turns a decimal string into a float.

    Returns:
        The number, or `value` unchanged when it is not a numeric string.

    Example:
        >>> to_int("3")
        3
        >>> to_int("3.5")
        '3.5'
        >>> to_int("3.5", as_int=False)
        3.5
        >>> to_int("+966")
        '+966'
    """
    if not isinstance(value, str) or value.startswith("+"):
        return value

    try:
        return int(value) if (as_int or "." not in value) else float(value)
    except (ValueError, TypeError):
        return value


def to_int_deep(
    data: NestedContainer[_T], as_int: bool = False
) -> NestedContainer[_T | int | float]:
    """Apply `to_int` to every leaf under `data`, mapping keys included.

    Args:
        data: A leaf, or a container or mapping of them, at any depth.
        as_int: `to_int`'s flag; `False` lets `"3.5"` become a float.

    Returns:
        The structure with numeric strings converted.

    Example:
        >>> to_int_deep({"a": ["1", "2.5"]})
        {'a': [1, 2.5]}
    """
    return map_deep(data, lambda value: to_int(value, as_int))


@overload
def calc(value: str, as_int: _False = False) -> StrInt | float: ...
@overload
def calc(value: str, as_int: _True) -> StrInt: ...
@overload
def calc(value: str, as_int: bool) -> StrInt | float: ...
@overload
def calc(value: _T, as_int: bool = False) -> _T: ...
def calc(value: Any, as_int: bool = False) -> Any:
    """Evaluate a string of simple arithmetic (`+ - * /`) safely, or read a plain number.

    Only `CALC_EXPRESSION_CHARS` are evaluated, through an allow-listed syntax
    tree, never `eval`. A failed evaluation is logged at DEBUG and the text
    returned.

    Args:
        value: The expression; anything that is not a string is returned as is.
        as_int: Whether to truncate a float result to an int; an infinite
            result cannot be, so the text is returned instead.

    Returns:
        The result, or `value` itself when it cannot be evaluated.

    Example:
        >>> calc("2 + 3 * 4")
        14
        >>> calc("7 / 2")
        3.5
        >>> calc("7 / 2", as_int=True)
        3
        >>> calc("abc")
        'abc'
    """
    if not isinstance(value, str):
        return value

    result = to_int(value, False)

    if isinstance(result, str):
        text = clean_spaces(result)

        if text and all(i in CALC_EXPRESSION_CHARS for i in text):
            try:
                result = _eval_calc_ast(ast.parse(text, mode="eval"))
            except Exception as e:
                log.debug("Failed to evaluate calculation expression: %s", text, exc_info=e)

    if as_int and isinstance(result, float):
        return int(result) if math.isfinite(result) else value

    return result


__all__ = (
    "to_int",
    "to_int_deep",
    "calc",
)
