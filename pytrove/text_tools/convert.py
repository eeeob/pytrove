"""Converting values to text, cleaning it, and changing its case style."""

from __future__ import annotations as _annotations

import re
from typing import Any

from ..typings import _T
from ..validate_tools import is_container
from ._internal import _SNAKE1_PATTERN, _SNAKE2_PATTERN


def to_str(value: _T) -> str | _T:
    """Turn a value into a string, leaving strings, bools, `None` and containers as they are.

    Args:
        value: The value to convert.

    Returns:
        `str(value)`, or `value` itself when it is `None`, a bool, a string or a container.
    """
    if value is None or isinstance(value, (bool, str)) or is_container(value):
        return value
    return str(value)


def clean_spaces(text: Any, with_lines: bool = True) -> str:
    """Remove whitespace from text.

    Args:
        text: The text, or a value `to_str` turns into text.
        with_lines: Whether line breaks go too; otherwise only other whitespace is removed.

    Returns:
        The text without whitespace.
    """
    text = to_str(text)
    return re.sub(r"\s+", "", text) if with_lines else re.sub(r"[^\S\n]+", "", text)


def split_part(
    value: str,
    sep: str,
    part: int = 0,
    strip: bool = True,
    remove_spaces: bool = False,
    default: _T | type[object] = object,
) -> str | _T:
    """Split `value` on `sep` and return one part.

    Args:
        value: The text to split.
        sep: The separator.
        part: The index of the part to return.
        strip: Whether to strip surrounding whitespace from the part.
        remove_spaces: Whether to remove all whitespace from the part.
        default: What to return when `part` is out of range; `value` itself when omitted.

    Returns:
        The selected part, cleaned as asked.
    """
    try:
        selected = value.split(sep)[part]
    except IndexError:
        return value if default is object else default

    if strip:
        selected = selected.strip()

    if remove_spaces:
        selected = clean_spaces(selected)

    return selected


def to_snake_case(text: str) -> str:
    """Turn `camelCase` or `PascalCase` into `snake_case`.

    Args:
        text: The text to convert.

    Returns:
        The text in lowercase, with an underscore before each word that began with a capital.
    """
    return _SNAKE2_PATTERN.sub(r"\1_\2", _SNAKE1_PATTERN.sub(r"\1_\2", text)).lower()


def to_pascal_case(text: str) -> str:
    """Turn `snake_case` or `camelCase` into `PascalCase`.

    Args:
        text: The text to convert.

    Returns:
        Each word capitalised and joined with no separator.
    """
    return "".join(word.title() for word in to_snake_case(text).split("_") if word)


__all__ = (
    "to_str",
    "clean_spaces",
    "split_part",
    "to_snake_case",
    "to_pascal_case",
)
