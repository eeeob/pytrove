"""Compiled regular expressions for email addresses and Telegram links and commands."""

from __future__ import annotations as _annotations

import re
from typing import Final

EMAIL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)
"""A plain email address: local part, `@`, a domain with a dot and a 2+ letter suffix."""

TG_BOT_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(r"^/[A-Za-z][\w\d]*$")
"""A bot command: a slash, a letter, then letters, digits or underscores."""

TG_CHANNEL_MESSAGE_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t(?:elegram)?\.(?:org|me|dog)/(?:c/)?)([\w]+)(?:/\d+)*/(\d+)/?$"
)
"""A link to a message in a channel, public (`t.me/name/5`) or private (`t.me/c/123/5`); groups 1 and 2 are the chat and the message id."""

TG_CHAT_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t(?:elegram)?\.(?:org|me|dog)/(?:c/)?)([\w]+)(?:.+)?$"
)
"""A `t.me` chat or message link; group 1 is the username or numeric id."""

TG_INVITE_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t(?:elegram)?\.(?:org|me|dog)/(?:joinchat/|\+))([\w-]+)$"
)
"""A `t.me/+hash` or `joinchat` invite link; group 1 is the hash (the same as Pyrogram's `Client.INVITE_LINK_RE`)."""

__all__ = (
    "EMAIL_PATTERN",
    "TG_BOT_COMMAND_PATTERN",
    "TG_CHANNEL_MESSAGE_LINK_PATTERN",
    "TG_CHAT_LINK_PATTERN",
    "TG_INVITE_LINK_PATTERN",
)
