"""Helpers private to `text_tools`."""

from __future__ import annotations as _annotations

import re
import sys
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

_SNAKE1_PATTERN: Final[re.Pattern[str]] = re.compile(r"([^_])([A-Z][a-z]+)")
"""A capitalised word that follows anything but `_`, as in `getHTTPResponse` -> `getHTTP_Response`."""

_SNAKE2_PATTERN: Final[re.Pattern[str]] = re.compile(r"([a-z0-9])([A-Z])")
"""A capital that follows a lowercase letter or digit, as in `getHTTP` -> `get_HTTP`."""

_WHITESPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
"""A run of whitespace, for `clean_spaces` and `smart_split(remove_spaces=True)`."""

_SPACES_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\S\n]+")
r"""A run of whitespace other than `\n`, for `clean_spaces(include_newlines=False)`."""


def _cut_piece(text: str, start: int, end: int, max_length: int, reverse: bool) -> int:
    """Find where `chunk_text` cuts the next piece of at most `max_length` off `text[start:end]`.

    The search window is `max_length + 1` long, so a break just past the limit
    still counts; the break character is left out of the piece. A newline wins,
    then a space that leaves a piece longer than `max_length // 10`, else the
    cut is hard. Only the window is searched, so a whole split stays linear.

    Args:
        text: The whole text.
        start: Where the text still to split begins.
        end: Where the text still to split ends.
        max_length: The longest the piece may be; at least 1.
        reverse: Whether to cut from the end instead of the start.

    Returns:
        The cut offset: the piece is `text[start:cut]`, or `text[cut:end]`
        with `reverse`; the rest is the other side of it.
    """
    if end - start <= max_length:
        return start if reverse else end

    for separator, shortest in (("\n", 0), (" ", max_length // 10)):
        if reverse:
            index = text.find(separator, end - max_length - 1, end)
            if index >= 0 and end - index - 1 > shortest:
                return index + 1
        else:
            index = text.rfind(separator, start, start + max_length + 1)
            if index >= 0 and index - start > shortest:
                return index

    return end - max_length if reverse else start + max_length


def _exc_tree_lines(
    error: BaseException | None, level: int, seen: set[int], connector: str = "└─"
) -> Iterator[str]:
    """Render `error` and the exceptions after it for `format_exc_tree`.

    The chain follows `__cause__`, else `__context__` unless
    `__suppress_context__` hides it, as `traceback` does. An exception group
    lists its members one level deeper, each marked `├─`, before its own
    cause, so a member never reads as the next link of the chain.

    Args:
        error: The exception to start from; `None` renders nothing.
        level: The depth of `error`.
        seen: The ids already rendered, shared by the whole walk to stop at a cycle.
        connector: The marker of `error`'s own line; the rest of its chain uses `└─`.

    Yields:
        One `└─ Type: message` line per exception (`├─` for a group member),
        continuation lines aligned under it.
    """
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        pad = "    " * level
        message = str(error).replace("\n", f"\n{pad}   ")
        yield f"{pad}{connector} {type(error).__name__}: {message}"
        connector = "└─"
        level += 1

        if sys.version_info >= (3, 11) and isinstance(error, BaseExceptionGroup):  # noqa: F821 - a 3.11 builtin; `ruff` ignores the version check
            for member in error.exceptions:
                yield from _exc_tree_lines(member, level, seen, "├─")

        if error.__cause__ is not None:
            error = error.__cause__
        else:
            error = None if error.__suppress_context__ else error.__context__


__all__ = (
    "_cut_piece",
    "_exc_tree_lines",
    "_SNAKE1_PATTERN",
    "_SNAKE2_PATTERN",
    "_SPACES_PATTERN",
    "_WHITESPACE_PATTERN",
)
