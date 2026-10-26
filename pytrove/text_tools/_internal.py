"""Helpers private to `text_tools`."""

from __future__ import annotations as _annotations

import re
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Callable

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


def _cut_piece(text: str, max_length: int, reverse: bool) -> tuple[str, str]:
    """Cut one piece of at most `max_length` characters off `text` for `chunk_text`.

    The search window is `max_length + 1` long, so a break just past the limit
    still counts; the break character itself is dropped. A newline wins, then a
    space that leaves a piece longer than `max_length // 10`, else the cut is hard.

    Args:
        text: The text still to split.
        max_length: The longest the piece may be; at least 1.
        reverse: Whether to cut from the end of `text` instead of the start.

    Returns:
        The piece, unstripped, and the text left once it is cut off.
    """
    if len(text) <= max_length:
        return text, ""

    window = text[-max_length - 1 :] if reverse else text[: max_length + 1]
    size, skip = max_length, 0

    for separator, shortest in (("\n", 0), (" ", max_length // 10)):
        index = window.find(separator) if reverse else window.rfind(separator)
        length = max_length - index if reverse else index

        if index >= 0 and length > shortest:
            size, skip = length, 1
            break

    if reverse:
        return text[len(text) - size :], text[: len(text) - size - skip]

    return text[:size], text[size + skip :]


__all__ = (
    "_cut_piece",
    "_smart_split_part",
    "_SNAKE1_PATTERN",
    "_SNAKE2_PATTERN",
)
