"""Laying text out: chunking long text, numbering lines, rendering exception chains."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, Any, overload

from ..enums import TgMessageLength
from ..iter_tools import to_list
from ..validate_tools import is_mapping
from ._internal import _cut_piece, _exc_tree_lines

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ..typings import Container, ContainerWithoutMapping, _KT, _T, _VT


def chunk_text(
    text: str, max_length: int = TgMessageLength.TEXT, reverse: bool = False
) -> list[str]:
    r"""Split text into pieces of at most `max_length` characters, avoiding mid-word cuts.

    The whole text is stripped first, and so is the whitespace left at each
    cut, so a blank line or a run of spaces takes no room in a piece. Each
    piece breaks at the last newline that fits, else at the last space that
    leaves it longer than `max_length // 10` (an earlier one would leave a
    near-empty piece), else hard at `max_length`. A break just past the limit
    counts too, since the break character itself is dropped. With `reverse`,
    the search is mirrored: pieces are cut from the end, at the first fitting
    break, so the piece holding the end of the text is the full one. Pieces
    are stripped, so none is blank. The work is linear in the text length.

    Only `\n` and the space are break characters: `\r\n` works, since the
    `\r` is stripped, but a lone `\r`, `\v`, `\f` or other line separator
    is not a line break.

    Args:
        text: The text to split.
        max_length: The longest a piece may be; Telegram's message limit by default.
        reverse: Whether to cut pieces from the end of the text.

    Returns:
        The pieces in the order they were cut: from the end of the text first
        when `reverse` is set; `[text.strip()]` when that fits, and `[]` when
        the text is blank.

    Raises:
        ValueError: If `max_length` is less than 1.

    Example:
        >>> chunk_text("one two three four", 9)
        ['one two', 'three', 'four']
        >>> chunk_text("one two three four", 9, reverse=True)
        ['four', 'two three', 'one']
    """
    if max_length < 1:
        msg = f"max_length must be at least 1, not {max_length!r}"
        raise ValueError(msg)

    text = text.strip()

    if len(text) <= max_length:
        return [text] if text else []

    chunks = []
    start, end = 0, len(text)

    # Offsets, not slices of the rest, keep the whole split linear.
    while start < end:
        cut = _cut_piece(text, start, end, max_length, reverse)

        if reverse:
            chunks.append(text[cut:end].strip())
            end = cut
            while end > start and text[end - 1].isspace():
                end -= 1
        else:
            chunks.append(text[start:cut].strip())
            start = cut
            while start < end and text[start].isspace():
                start += 1

    return chunks


def format_exc_tree(exc: BaseException) -> str:
    """Render an exception and its causes as an indented tree, one entry each.

    It follows `__cause__`, else `__context__` unless `raise ... from None`
    suppressed it, as `traceback` does, and stops at a cycle. An exception
    group (3.11+) lists its members one level deeper, each marked `├─`,
    before its own cause, which keeps the `└─` of the chain.

    Args:
        exc: The outermost exception.

    Returns:
        One `└─ Type: message` entry per exception (`├─` for a group member),
        each nested one level deeper; the lines of a multi-line message stay
        aligned under it.

    Example:
        >>> try:
        ...     try:
        ...         raise ValueError("bad value")
        ...     except ValueError as e:
        ...         raise RuntimeError("wrapper") from e
        ... except RuntimeError as err:
        ...     print(format_exc_tree(err))
        └─ RuntimeError: wrapper
            └─ ValueError: bad value
    """
    return "\n".join(_exc_tree_lines(exc, 0, set()))


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
    line_sep: None,
) -> list[str]: ...
@overload
def numbering(
    values: Mapping[_KT, _VT],
    start: int = 1,
    line_parser: Callable[[_KT, _VT, int], str] | None = None,
    *,
    line_sep: None,
) -> list[str]: ...
@overload
def numbering(
    values: ContainerWithoutMapping[_T],
    start: int,
    line_parser: Callable[[_T, int], str] | None,
    line_sep: None,
) -> list[str]: ...
@overload
def numbering(
    values: Mapping[_KT, _VT],
    start: int,
    line_parser: Callable[[_KT, _VT, int], str] | None,
    line_sep: None,
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

    Example:
        >>> print(numbering(["a", "b"]))
        1. a
        2. b
        >>> numbering({"a": 1}, start=0)
        '0. a - 1'
        >>> numbering(["a", "b"], line_parser=lambda v, n: f"{n}) {v}", line_sep=None)
        ['1) a', '2) b']
    """
    is_map = is_mapping(values)
    items = to_list(values.items() if is_map else values)

    if is_map:
        pair_parser = (
            line_parser if line_parser is not None else (lambda k, v, c: f"{c}. {k} - {v}")
        )
        lines = [
            pair_parser(key, value, counter) for counter, (key, value) in enumerate(items, start)
        ]
    else:
        value_parser = line_parser if line_parser is not None else (lambda v, c: f"{c}. {v}")
        lines = [value_parser(value, counter) for counter, value in enumerate(items, start)]

    return lines if line_sep is None else line_sep.join(lines)


__all__ = (
    "chunk_text",
    "format_exc_tree",
    "numbering",
)
