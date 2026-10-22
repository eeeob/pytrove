"""Reading numbers out of strings, and evaluating simple arithmetic."""

from __future__ import annotations as _annotations

import ast
import logging
from typing import TYPE_CHECKING, Any, Final, overload

from ..data_tools import map_deep
from ..text_tools import clean_spaces
from ._internal import _eval_calc_ast

if TYPE_CHECKING:
    from ..typings import NestedContainer, StrInt, _False, _T, _True

CALC_ALLOWED_CHARS: Final[frozenset[str]] = frozenset("0123456789*/-+.")
"""The only characters `calc` will evaluate; whitespace is removed first."""

log = logging.getLogger(__name__)


@overload
def to_int(value: str, as_int: _True = ...) -> StrInt: ...
@overload
def to_int(value: str, as_int: _False) -> StrInt | float: ...
@overload
def to_int(value: _T, as_int: bool = ...) -> _T: ...
def to_int(value: Any, as_int: bool = True) -> Any:
    """Turn a numeric string into a number, leaving everything else as it is.

    A string starting with `+` is kept as text, since it is usually a phone number.

    Args:
        value: The value to convert.
        as_int: Whether a decimal string must become an int; otherwise it becomes a float.

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


def to_int_deep(data: NestedContainer[_T], as_int: bool = False) -> NestedContainer[_T | int | float]:
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
def calc(value: str, as_int: _False = ...) -> StrInt | float: ...
@overload
def calc(value: str, as_int: _True) -> StrInt: ...
@overload
def calc(value: _T, as_int: bool = ...) -> _T: ...
def calc(value: Any, as_int: bool = False) -> Any:
    """Evaluate a string of simple arithmetic (`+ - * /`) safely, or read a plain number.

    Only `CALC_ALLOWED_CHARS` are evaluated, through an allow-listed syntax
    tree, never `eval`. A failed evaluation is logged and the text returned.

    Args:
        value: The expression; anything that is not a string is returned as is.
        as_int: Whether to truncate a float result to an int.

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

    value = to_int(value, False)

    if isinstance(value, str):
        c_value: Any = clean_spaces(value)

        if all(i in CALC_ALLOWED_CHARS for i in c_value):
            try:
                c_value = _eval_calc_ast(ast.parse(c_value, mode="eval"))
            except Exception as e:
                log.error("Failed to evaluate calculation expression: %s", c_value, exc_info=e)

        if isinstance(c_value, (int, float)):
            value = c_value

    if as_int and isinstance(value, float):
        value = int(value)

    return value


__all__ = (
    "to_int",
    "to_int_deep",
    "calc",
    "CALC_ALLOWED_CHARS",
)
