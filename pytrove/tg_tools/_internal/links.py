"""Helpers private to `tg_tools`: link formatting details."""

from __future__ import annotations as _annotations

import re
from typing import Final

_PRIVATE_CHAT_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:https?://)?(?:www\.)?t(?:elegram)?\.(?:org|me|dog)/c/(\d+\S*)$", re.IGNORECASE
)
"""A `t.me/c/<id>/...` private-channel link; group 1 is everything after `/c/`."""

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
    "_PRIVATE_CHAT_LINK_PATTERN",
    "_SHORT_LINK_TEXT",
)
