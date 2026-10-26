"""Sets of characters an input is checked against."""

from __future__ import annotations as _annotations

from typing import Final

CALC_EXPRESSION_CHARS: Final[frozenset[str]] = frozenset("0123456789*/-+.")
"""The only characters `calc` will evaluate; whitespace is removed first."""

__all__ = ("CALC_EXPRESSION_CHARS",)
