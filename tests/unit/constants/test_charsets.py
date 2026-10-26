"""`pytrove.constants.charsets`: the character sets inputs are checked against."""

from __future__ import annotations as _annotations

from pytrove.constants import charsets
from pytrove.constants.charsets import CALC_EXPRESSION_CHARS


def test_calc_expression_chars_are_digits_operators_and_the_point() -> None:
    assert frozenset("0123456789*/-+.") == CALC_EXPRESSION_CHARS


def test_all_lists_exactly_the_charsets() -> None:
    assert charsets.__all__ == ("CALC_EXPRESSION_CHARS",)
