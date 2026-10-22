"""Helpers private to `text_tools`."""

from __future__ import annotations as _annotations

import re
from collections.abc import Callable
from typing import Any, Final

_SNAKE1_PATTERN: Final[re.Pattern[str]] = re.compile(r"(.)([A-Z][a-z]+)")
"""A capitalised word that follows any character, as in `getHTTPResponse` -> `getHTTP_Response`."""

_SNAKE2_PATTERN: Final[re.Pattern[str]] = re.compile(r"([a-z0-9])([A-Z])")
"""A capital that follows a lowercase letter or digit, as in `getHTTP` -> `get_HTTP`."""


def _smart_split_part(
    text: str,
    part_filter: Callable[[str], bool] | None,
    strip: bool,
    remove_spaces: bool,
    resolver: Callable[[str], Any] | None,
) -> tuple[bool, Any]:
    """Filter, clean and convert one part for `smart_split`.

    The filter sees the raw part, before any cleaning.

    Args:
        text: The raw part.
        part_filter: Keeps the part when it returns true; `None` keeps everything.
        strip: Whether to strip surrounding whitespace.
        remove_spaces: Whether to remove all whitespace; overrides `strip`.
        resolver: Converts the cleaned part; `None` leaves it a string.

    Returns:
        Whether the part is kept, and the part itself once cleaned and converted.
    """
    from .convert import clean_spaces  # noqa: PLC0415 - `convert` imports this module

    if part_filter is not None and not part_filter(text):
        return False, None

    if remove_spaces:
        text = clean_spaces(text)
    elif strip:
        text = text.strip()

    return True, resolver(text) if resolver is not None else text


__all__ = (
    "_smart_split_part",
    "_SNAKE1_PATTERN",
    "_SNAKE2_PATTERN",
)
