"""Splitting text into Telegram-sized messages."""

from __future__ import annotations as _annotations

from ..enums import TgMessageLength
from ..text_tools import chunk_text


def split_tg_message(
    text: str, length: int = TgMessageLength.TEXT, reverse: bool = False
) -> list[str]:
    r"""Split text into messages of at most `length` characters, as `chunk_text` does.

    The whole text is stripped first. Messages break between lines where they
    can, and a line longer than `length` breaks at a space, or hard. A break
    just past the limit counts, so messages come out as full as they can.
    Blank messages are dropped. With `reverse`, messages are cut from the end,
    so the message holding the end of the text is the full one.

    Only `\n` breaks lines: `\r\n` works, but a lone `\r`, `\v`, `\f`,
    `\x1c`-`\x1e`, `\x85`, `\u2028` or `\u2029` is no longer a line break, as
    it was with `str.splitlines`. A long line used to be cut hard; it now breaks
    at a space when one leaves a message longer than `length // 10`.

    Args:
        text: The text; surrounding whitespace is stripped.
        length: The longest a message may be; Telegram's limit by default.
        reverse: Whether to fill messages from the end.

    Returns:
        The messages, stripped, in the order they were cut: from the end of
        the text first when `reverse` is set.

    Raises:
        ValueError: If `length` is less than 1 (raised by `chunk_text`, whose
            message names `max_length`).

    Example:
        >>> split_tg_message("line one\nline two\nline three", 18)
        ['line one\nline two', 'line three']
        >>> split_tg_message("line one\nline two\nline three", 18, reverse=True)
        ['line three', 'line one\nline two']
    """
    return chunk_text(text.strip(), length, reverse)


__all__ = ("split_tg_message",)
