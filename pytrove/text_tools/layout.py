"""Laying text out: chunking long text, numbering lines, rendering exception chains."""

from __future__ import annotations as _annotations

from collections.abc import Callable, Iterator, Mapping
from typing import Any, Literal, overload

from ..enums import TgMessageLength
from ..iter_tools import to_list
from ..typings import Container, ContainerWithoutMapping, _KT, _T, _VT
from ..validate_tools import is_mapping


def chunk_text(text: str, max_length: int = TgMessageLength.TEXT) -> list[str]:
    """Split text into pieces of at most `max_length` characters, avoiding mid-word cuts.

    Within each window it breaks at the last newline, else at the last space
    in the window's later 90% (an earlier one would leave a near-empty piece),
    else hard at `max_length`. Pieces are stripped, and blank ones dropped.

    Args:
        text: The text to split.
        max_length: The longest a piece may be; Telegram's message limit by default.

    Returns:
        The pieces in order; `[text]` when it already fits.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        chunk = remaining[:max_length]

        if len(remaining) <= max_length:
            remaining = ""
        elif (last_newline := chunk.rfind("\n")) > 0:
            chunk = chunk[:last_newline]
            remaining = remaining[last_newline + 1:]
        elif (last_space := chunk.rfind(" ")) > len(chunk) // 10:
            chunk = chunk[:last_space]
            remaining = remaining[last_space + 1:]
        else:
            remaining = remaining[max_length:]

        if chunk.strip():
            chunks.append(chunk.strip())

    return chunks


def format_exc_tree(exc: BaseException) -> str:
    """Render an exception and its causes as an indented tree, one line each.

    It follows `__cause__`, else `__context__`, as `traceback` does, and stops
    at a cycle.

    Args:
        exc: The outermost exception.

    Returns:
        One `└─ Type: message` line per exception, each nested one level deeper.
    """

    def iter_exc() -> Iterator[tuple[int, BaseException]]:
        """Walk the chain once.

        Yields:
            Each exception with its depth.
        """
        current: BaseException | None = exc
        level = 0
        seen: set[int] = set()

        while current is not None and id(current) not in seen:
            seen.add(id(current))
            yield level, current
            current = current.__cause__ or current.__context__
            level += 1

    return "\n".join(f"{'    ' * level}└─ {type(error).__name__}: {error}" for level, error in iter_exc())


@overload
def numbering(
    values: ContainerWithoutMapping[_T],
    start: int = 1,
    line_parser: Callable[[_T, int], str] | None = None,
    line_sep: str = "\n",
) -> str: ...
@overload
def numbering(
    values: Mapping[_KT, _VT],
    start: int = 1,
    line_parser: Callable[[_KT, _VT, int], str] | None = None,
    line_sep: str = "\n",
) -> str: ...
@overload
def numbering(
    values: ContainerWithoutMapping[_T],
    start: int = 1,
    line_parser: Callable[[_T, int], str] | None = None,
    *,
    line_sep: Literal[None],
) -> list[str]: ...
@overload
def numbering(
    values: Mapping[_KT, _VT],
    start: int = 1,
    line_parser: Callable[[_KT, _VT, int], str] | None = None,
    *,
    line_sep: Literal[None],
) -> list[str]: ...
def numbering(
    values: Container[Any],
    start: int = 1,
    line_parser: Callable[..., str] | None = None,
    line_sep: str | None = "\n",
) -> str | list[str]:
    """Number each value, or each mapping pair, as one line.

    Args:
        values: The values, or a mapping whose pairs are numbered.
        start: The first number.
        line_parser: Builds a line from `(value, n)`, or `(key, value, n)` for a
            mapping; `"n. value"` / `"n. key - value"` by default.
        line_sep: Joins the lines; `None` returns them as a list.

    Returns:
        The joined lines, or the list of them.
    """
    is_map = is_mapping(values)
    items = to_list(values.items() if is_map else values)

    if is_map:
        pair_parser = line_parser if line_parser is not None else (lambda k, v, c: f"{c}. {k} - {v}")
        lines = [pair_parser(key, value, counter) for counter, (key, value) in enumerate(items, start)]
    else:
        value_parser = line_parser if line_parser is not None else (lambda v, c: f"{c}. {v}")
        lines = [value_parser(value, counter) for counter, value in enumerate(items, start)]

    return lines if line_sep is None else line_sep.join(lines)


__all__ = (
    "chunk_text",
    "format_exc_tree",
    "numbering",
)
