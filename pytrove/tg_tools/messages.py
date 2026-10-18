"""Splitting text into Telegram-sized messages."""

from __future__ import annotations as _annotations

from collections.abc import Iterable

from ..enums import TgMessageLength


def split_tg_message(text: str, length: int = TgMessageLength.TEXT, reverse: bool = False) -> list[str]:
    """Split text into messages of at most `length` characters, breaking between lines.

    A line longer than `length` is cut hard. With `reverse`, lines are packed
    from the end, so the last message is the full one.

    Args:
        text: The text; surrounding whitespace is stripped.
        length: The longest a message may be; Telegram's limit by default.
        reverse: Whether to fill messages from the end.

    Returns:
        The messages, stripped, in reading order of how they were packed.
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
