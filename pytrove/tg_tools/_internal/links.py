"""Helpers private to `tg_tools`: link formatting details and the one target classifier."""

from __future__ import annotations as _annotations

import re
from typing import Final, Literal, TypeAlias

from ...constants import TG_CHAT_LINK_PATTERN, TG_INVITE_LINK_PATTERN

_PRIVATE_CHAT_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.(?:me|dog|org))/c/(\d+(?:/\S*)?)\Z", re.IGNORECASE
)
"""A `t.me/c/<id>/...` private-channel link; group 1 is the numeric id and whatever path follows it."""

_PREVIEW_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.(?:me|dog|org))/s/(\w+)(?:/\S*)?\Z", re.IGNORECASE
)
"""A `t.me/s/<name>` web preview of a public channel; group 1 is the name."""

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

_TgTargetKind: TypeAlias = Literal["invite", "private", "link", "text"]
"""What `_classify_tg_target` found: an invite link, a `/c/` link, a chat link, or plain text."""


def _classify_tg_target(text: str) -> tuple[_TgTargetKind, str]:
    """Sort a stripped Telegram target, matching every link pattern regardless of case.

    Args:
        text: The target, already stripped of surrounding whitespace.

    Returns:
        The kind and its value: an invite link as given; the path after `/c/`;
        the lowercased name or id a chat or preview link captures; or the text
        as given.

    Example:
        >>> _classify_tg_target("HTTPS://T.ME/+AbCd")
        ('invite', 'HTTPS://T.ME/+AbCd')
        >>> _classify_tg_target("t.me/c/123/4")
        ('private', '123/4')
        >>> _classify_tg_target("t.me/s/Name")
        ('link', 'name')
        >>> _classify_tg_target("@Name")
        ('text', '@Name')
    """
    lowered = text.lower()

    # The invite pattern goes first: `TG_CHAT_LINK_PATTERN` also matches a `joinchat/` link.
    if TG_INVITE_LINK_PATTERN.match(lowered):
        return "invite", text

    # Before `TG_CHAT_LINK_PATTERN` too: it would read the channel id after `/c/` as a name,
    # and the `s` of a `/s/` preview link as one.
    if private := _PRIVATE_CHAT_LINK_PATTERN.match(text):
        return "private", private.group(1)

    if preview := _PREVIEW_LINK_PATTERN.match(lowered):
        return "link", preview.group(1)

    if match := TG_CHAT_LINK_PATTERN.match(lowered):
        return "link", match.group(1)

    return "text", text


__all__ = (
    "_HIDDEN_PADDING",
    "_SHORT_LINK_TEXT",
    "_classify_tg_target",
)
