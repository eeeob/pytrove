"""Phone-number text cleanup shared by `phone_tools.parse_phone` and `validate_tools.is_phone_number`."""

from __future__ import annotations as _annotations

import re


def _normalize_phone_text(text: str, clean: bool = True, resolve: bool = True) -> str:
    """Prepare phone-number text for `phonenumbers.parse`.

    Args:
        text: The number as text.
        clean: Whether to remove whitespace and dashes.
        resolve: Whether to turn a `00` prefix, or no prefix, into `+`.

    Returns:
        The prepared text.

    Example:
        >>> _normalize_phone_text("00966 50-123")
        '+96650123'
        >>> _normalize_phone_text("966 50", clean=False, resolve=False)
        '966 50'
    """
    if clean:
        text = re.sub(r"[\s-]+", "", text)

    if resolve:
        if text.startswith("00"):
            text = text[2:]

        if not text.startswith("+"):
            text = "+" + text

    return text


__all__ = ("_normalize_phone_text",)
