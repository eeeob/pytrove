"""Splitting text into Telegram-sized messages."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

from ..enums import TgMessageLength

if TYPE_CHECKING:
    from collections.abc import Iterable


def split_tg_message(
    text: str, length: int = TgMessageLength.TEXT, reverse: bool = False
) -> list[str]:
    r"""Split text into messages of at most `length` characters, breaking between lines.

    A line longer than `length` is cut hard, and a chunk that is only
    whitespace is dropped. With `reverse`, lines are packed from the end, so
    the message holding the end of the text is the full one.

    Args:
        text: The text; surrounding whitespace is stripped.
        length: The longest a message may be; Telegram's limit by default.
        reverse: Whether to fill messages from the end.

    Returns:
        The messages, stripped, in the order they were packed: from the end
        of the text first when `reverse` is set.

    Example:
        >>> split_tg_message("line one\nline two\nline three", 18)
        ['line one\nline two', 'line three']
        >>> split_tg_message("line one\nline two\nline three", 18, reverse=True)
        ['line three', 'line one\nline two']
    """
    text = text.strip()

    if len(text) <= length:
        return [text]

    lines: Iterable[str] = text.splitlines(True)

    if reverse:
        lines = reversed(list(lines))

    messages: list[str] = []
    current = ""

    for line in lines:
        if len(current) + len(line) <= length:
            current = (line + current) if reverse else (current + line)
            continue

        if current:
            messages.append(current)

        current = line

        while len(current) > length:
            if reverse:
                messages.append(current[-length:])
                current = current[:-length]
            else:
                messages.append(current[:length])
                current = current[length:]

    # `text` is longer than `length`, so there is at least one line, and every
    # line leaves a non-empty remainder of at most `length` in `current`.
    messages.append(current)

    return [m.strip() for m in messages if m.strip()]


__all__ = ("split_tg_message",)
