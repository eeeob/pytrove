r"""Compiled regular expressions for email addresses and Telegram links and commands.

Every pattern ends in `\Z`, not `$`, so `match` alone rejects a trailing newline.
The Telegram link hosts are `t.me`, `telegram.me`, `telegram.dog` and `telegram.org`.
"""

from __future__ import annotations as _annotations

import re
from typing import Final

EMAIL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\Z"
)
"""A plain email address: local part, `@`, a domain with a dot and a 2+ letter suffix."""

TG_BOT_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^/[A-Za-z][A-Za-z0-9_]*(?:@[A-Za-z0-9_]+)?\Z"
)
"""A bot command: a slash, an ASCII letter, then ASCII letters, digits or underscores.

An optional `@botname` suffix, the form Telegram sends in groups (`/start@my_bot`), is
accepted. Non-ASCII letters are not: Telegram commands are ASCII only.
"""

TG_CHANNEL_MESSAGE_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:(?:t\.me|telegram\.(?:me|dog|org))/(?:c/)?)([\w]+)(?:/\d+)*/(\d+)/?\Z"
)
"""A link to a message in a channel, public (`t.me/name/5`) or private (`t.me/c/123/5`); groups 1 and 2 are the chat and the message id."""

TG_CHAT_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:(?:t\.me|telegram\.(?:me|dog|org))/(?:c/)?)([\w]+)(?:.+)?\Z"
)
"""A `t.me` chat or message link; group 1 is the username or numeric id."""

TG_INVITE_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:(?:t\.me|telegram\.(?:me|dog|org))/(?:joinchat/|\+))([\w-]+)\Z"
)
"""A `t.me/+hash` or `joinchat` invite link; group 1 is the hash (the same as Pyrogram's `Client.INVITE_LINK_RE`)."""

__all__ = (
    "EMAIL_PATTERN",
    "TG_BOT_COMMAND_PATTERN",
    "TG_CHANNEL_MESSAGE_LINK_PATTERN",
    "TG_CHAT_LINK_PATTERN",
    "TG_INVITE_LINK_PATTERN",
)
