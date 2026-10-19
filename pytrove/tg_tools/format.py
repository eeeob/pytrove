"""Reading and writing Telegram usernames, links, targets and mentions."""

from __future__ import annotations as _annotations

import re
from typing import Any, Final, overload

try:
    from pyrogram.enums import ParseMode
    from pyrogram.types import CallbackQuery as Query, Chat, Message, User
    from pyrogram.types.user_and_chats.user import Link
    from pyrogram.utils import get_channel_id
except ImportError:
    pass

from .._internal._optional import _optional_import
from ..errors import ValidationError
from ..num_tools import to_int
from ..text_tools import clean_spaces
from ..typings import StrInt, _T
from ..validate_tools import is_tg_user_id
from ._internal.links import _HIDDEN_PADDING, _PRIVATE_CHAT_LINK_PATTERN, _SHORT_LINK_TEXT

CHAT_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t(?:elegram)?\.(?:org|me|dog)/(?:c/)?)([\w]+)(?:.+)?$"
)
"""A `t.me` chat or message link; group 1 is the username or numeric id."""

INVITE_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t(?:elegram)?\.(?:org|me|dog)/(?:joinchat/|\+))([\w-]+)$"
)
"""A `t.me/+hash` or `joinchat` invite link; group 1 is the hash (the same as Pyrogram's `Client.INVITE_LINK_RE`)."""


@_optional_import(("kurigram", "tg"))
def extract_pyro_update_text(update: Message | Query) -> str | bytes:
    """Return the text of a message (or its caption) or the data of a callback query.

    Args:
        update: The update.

    Returns:
        The text, or an empty string when it has none.

    Raises:
        ValidationError: For any other kind of update.
    """
    if isinstance(update, Message):
        return update.text or update.caption or ""

    if isinstance(update, Query):
        return update.data or ""

    msg = f"extract_pyro_update_text doesn't work with {type(update)}"
    raise ValidationError(msg)


@overload
def format_tg_username(target: str | Chat | User, with_invite_link: bool = False, with_at: bool = True) -> str | None: ...
@overload
def format_tg_username(
    target: str | Chat | User, with_invite_link: bool = False, with_at: bool = True, default: _T = ...,
) -> str | _T: ...
@_optional_import(("kurigram", "tg"))
def format_tg_username(
    target: str | Chat | User, with_invite_link: bool = False, with_at: bool = True, default: Any = None,
) -> Any:
    """Normalise a username, `t.me` link or chat into a username.

    Args:
        target: A username, a link, or a `User`/`Chat`.
        with_invite_link: Whether an invite link is returned as it is instead of `default`.
        with_at: Whether to prefix `@`.
        default: Returned when there is no username.

    Returns:
        The username, the invite link, or `default`.
    """
    text = target.username if isinstance(target, (User, Chat)) else target

    if not text:
        return default

    # The invite pattern goes first: `CHAT_LINK_PATTERN` also matches a `joinchat/` link.
    if INVITE_LINK_PATTERN.match(text.lower()):
        return text if with_invite_link else default

    match = CHAT_LINK_PATTERN.match(text.lower())
    name = (match.group(1) if match else text.replace("@", "")).strip()
    return "@" + name if with_at else name


@overload
def format_tg_link(target: StrInt | Message | Chat | User) -> str | None: ...
@overload
def format_tg_link(target: StrInt | Message | Chat | User, default: _T) -> str | _T: ...
@_optional_import(("kurigram", "tg"))
def format_tg_link(target: StrInt | Message | Chat | User, default: Any = None) -> Any:
    """Build a link that opens a message, chat or user.

    A message gives its own `Message.link` (empty in a private chat); a
    username gives `https://t.me/<name>`; a user id `tg://openmessage?user_id=`;
    any other id `tg://openmessage?chat_id=`; an invite link is returned as it is;
    a `t.me/c/<id>/...` private-channel link keeps that form.

    Args:
        target: A message, chat, user, username, id or link.
        default: Returned when there is nothing to link to.

    Returns:
        The link, or `default`.
    """
    if isinstance(target, Message):
        return target.link

    if isinstance(target, (User, Chat)):
        key: StrInt | None = target.username or getattr(target, "invite_link", None) or target.id
    else:
        key = target

    if not key:
        return default

    text = str(key)

    # The invite pattern goes first: `CHAT_LINK_PATTERN` also matches a `joinchat/` link.
    if INVITE_LINK_PATTERN.match(text):
        return text

    # Before `CHAT_LINK_PATTERN` too: its capture of a `/c/` link is a channel id, not a user id.
    private = _PRIVATE_CHAT_LINK_PATTERN.match(text)

    if private:
        return f"https://t.me/c/{private.group(1)}"

    match = CHAT_LINK_PATTERN.match(text.lower())
    value = to_int((match.group(1) if match else text.replace("@", "")).strip())

    if not isinstance(value, int):
        return f"https://t.me/{value}"

    if is_tg_user_id(value):
        return f"tg://openmessage?user_id={value}"

    return f"tg://openmessage?chat_id={get_channel_id(value)}"


@_optional_import(("kurigram", "tg"))
def parse_tg_target(target: StrInt) -> StrInt:
    """Read a chat or user target down to what Pyrogram's methods accept.

    An int is kept; a phone number (after removing `+`, `()`, `-` and spaces)
    becomes its digits as an int; a channel link gives its id through
    `get_channel_id`, or its public name; an invite link is kept; anything
    else is a username without `@`, `+` or spaces, lowercased.

    Args:
        target: An id, phone number, link or username.

    Returns:
        An int where the target names one, a string otherwise.
    """
    if isinstance(target, int):
        return target

    target = clean_spaces(target)
    phone = re.sub(r"[+()\s-]", "", target)

    if phone.isdigit():
        return int(phone)

    # The invite pattern goes first: `CHAT_LINK_PATTERN` also matches a `joinchat/` link.
    if INVITE_LINK_PATTERN.match(target):
        return target

    match = CHAT_LINK_PATTERN.match(target.lower())

    if not match:
        return re.sub(r"[@+\s]", "", target.lower())

    try:
        return get_channel_id(int(match.group(1)))
    except ValueError:
        return match.group(1)


@_optional_import(("kurigram", "tg"))
def format_hidden_tg_link(url: str, text: str, parse_mode: ParseMode | None = None) -> str:
    """Format a link, padding very short text with invisible characters so clients keep it.

    Args:
        url: The target URL.
        text: The visible text.
        parse_mode: HTML by default.

    Returns:
        The formatted link markup.
    """
    if len(text) <= _SHORT_LINK_TEXT:
        text += _HIDDEN_PADDING

    return Link(url, text, ParseMode.HTML if parse_mode is None else parse_mode)()


@_optional_import(("kurigram", "tg"))
def mention_tg_user(user_id: int, user_full_name: str | None = None, parse_mode: ParseMode | None = None) -> str:
    """Format a mention that opens a user's profile.

    Args:
        user_id: The user's id.
        user_full_name: The visible name; `"Deleted Account"` when `None`.
        parse_mode: HTML by default.

    Returns:
        The formatted mention.
    """
    name = "Deleted Account" if user_full_name is None else user_full_name
    return format_hidden_tg_link(f"tg://user?id={user_id}", name, parse_mode)


__all__ = (
    "extract_pyro_update_text",
    "format_tg_username",
    "format_tg_link",
    "parse_tg_target",
    "format_hidden_tg_link",
    "mention_tg_user",
    "CHAT_LINK_PATTERN",
    "INVITE_LINK_PATTERN",
)
