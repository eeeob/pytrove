"""Helpers private to `tg_tools`: link formatting details."""

from __future__ import annotations as _annotations

from typing import Final

_SHORT_LINK_TEXT: Final[int] = 3
"""Link texts this short are padded, because some Telegram clients drop very short links."""

_HIDDEN_PADDING: Final[str] = (
    "\u206a\u206c\u206a\u206c\u206e\u206a\u206c\u206a\u206c\u206e\u206a\u206c\u206a\u206c"
    "\u206e\u206a\u206c\u206a\u206c\u206e\u206a\u206c\u206a\u206c\u206e\u206a\u206c\u206a"
    "\u206c\u206e\u206a\u206c\u206a\u206c\u206e\u206a\u206c\u206a\u206c\u206e\u206a\u206c"
    "\u206a\u206c\u206e\u206a\u206c\u206a\u206c\u206e\u206a\u206c\u206a\u206c\u206e\u206a"
    "\u206c\u206a\u206c\u206e \u206a\u206c\u206a\u206c\u206e\u206a\u206c\u206a\u206c"
    "\u206e \u206a\u206c"
)
"""Invisible formatting characters and spaces that lengthen a short link text without showing."""

__all__ = (
    "_HIDDEN_PADDING",
    "_SHORT_LINK_TEXT",
)
