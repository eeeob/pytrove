"""Reading and writing Telegram usernames, links, targets and mentions; splitting messages."""

from __future__ import annotations as _annotations

import re
from typing import TYPE_CHECKING, Any, overload

try:
    from pyrogram.enums import ParseMode  # type: ignore[import-not-found]  # Optional: the `tg` extra.
    from pyrogram.types import CallbackQuery as Query, Chat, Message, User  # type: ignore[import-not-found]  # Optional: the `tg` extra.
    from pyrogram.types.user_and_chats.user import Link  # type: ignore[import-not-found]  # Optional: the `tg` extra.
    from pyrogram.utils import get_channel_id, get_peer_type  # type: ignore[import-not-found]  # Optional: the `tg` extra.
except ImportError:
    pass

from .._internal import _optional_import
from ..errors import ValidationError
from ..num_tools import to_int
from ..text_tools import clean_spaces
from ._internal import _HIDDEN_PADDING, _SHORT_LINK_TEXT, _classify_tg_target

if TYPE_CHECKING:
    from ..typings import StrInt, _T


@_optional_import("tg")
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
def format_tg_username(
    target: str | Chat | User, allow_invite_link: bool = False, prefix_at: bool = True
) -> str | None: ...
@overload
def format_tg_username(
    target: str | Chat | User, allow_invite_link: bool, prefix_at: bool, default: _T
) -> str | _T: ...
@overload
def format_tg_username(
    target: str | Chat | User,
    allow_invite_link: bool = False,
    prefix_at: bool = True,
    *,
    default: _T,
) -> str | _T: ...
@_optional_import("tg")
def format_tg_username(
    target: str | Chat | User,
    allow_invite_link: bool = False,
    prefix_at: bool = True,
    default: Any = None,
) -> Any:
    """Normalise a username, `t.me` link or chat into a username.

    Links are recognised in any case; a `t.me/s/<name>` preview gives `<name>`.

    Args:
        target: A username, a link, or a `User`/`Chat`.
        allow_invite_link: Whether an invite link is returned as it is instead of `default`.
        prefix_at: Whether to prefix `@`.
        default: Returned when there is no username.

    Returns:
        The username, the invite link, or `default`, which is also what a
        private-channel link or text that is not a bare name (another site's
        URL, say) gives.
    """
    text = target.username if isinstance(target, (User, Chat)) else target
    text = (text or "").strip()

    if not text:
        return default

    kind, value = _classify_tg_target(text)

    if kind == "invite":
        return text if allow_invite_link else default

    # A private channel has no username.
    if kind == "private":
        return default

    name = value if kind == "link" else value.replace("@", "").strip()

    if not re.fullmatch(r"\w+", name):
        return default

    return "@" + name if prefix_at else name


@overload
def format_tg_link(target: StrInt | Message | Chat | User) -> str | None: ...
@overload
def format_tg_link(target: StrInt | Message | Chat | User, default: _T) -> str | _T: ...
@_optional_import("tg")
def format_tg_link(target: StrInt | Message | Chat | User, default: Any = None) -> Any:
    """Build a link that opens a message, chat or user.

    A message gives its own `Message.link`, or `default` when it has none
    (a private chat, for one); a username gives `https://t.me/<name>`; a user id
    `tg://openmessage?user_id=`; a basic-group or channel id
    `tg://openmessage?chat_id=` with its raw id; an invite link, in any case, is
    returned as it is; a `t.me/c/<id>/...` private-channel link keeps that form.
    An id Pyrogram reads as none of these gives `default`.

    Args:
        target: A message, chat, user, username, id or link.
        default: Returned when there is nothing to link to.

    Returns:
        The link, or `default`.
    """
    if isinstance(target, Message):
        return target.link or default

    if isinstance(target, (User, Chat)):
        key: StrInt | None = target.username or getattr(target, "invite_link", None) or target.id
    else:
        key = target

    if not key:
        return default

    # Stripped first: the anchored patterns would miss a padded link.
    kind, value = _classify_tg_target(str(key).strip())

    if kind == "invite":
        return value

    # Its capture is a channel id, not a user id.
    if kind == "private":
        return f"https://t.me/c/{value}"

    peer = to_int(value if kind == "link" else value.replace("@", "").strip())

    if not isinstance(peer, int):
        return f"https://t.me/{peer}"

    try:
        peer_type = get_peer_type(peer)
    except ValueError:
        return default

    if peer_type == "user":
        return f"tg://openmessage?user_id={peer}"

    # A basic group's raw id is its negated id; only a channel id carries the `-100` offset.
    if peer_type == "chat":
        return f"tg://openmessage?chat_id={-peer}"

    if peer_type in {"channel", "monoforum"}:
        return f"tg://openmessage?chat_id={get_channel_id(peer)}"

    return default


@_optional_import("tg")
def parse_tg_target(target: StrInt) -> StrInt:
    """Read a chat or user target down to what Pyrogram's methods accept.

    An int is kept, and so is the sign of a numeric string (`"-100..."`); a
    phone number (after removing `+`, `()`, `-` and spaces) becomes its digits
    as an int; a `t.me/c/<id>` link gives its chat id through `get_channel_id`,
    and a chat link its public name; an invite link is kept as given; anything
    else is a username without `@`, `+` or spaces, lowercased. Links are
    recognised in any case.

    Args:
        target: An id, phone number, link or username.

    Returns:
        An int where the target names one, a string otherwise.
    """
    if isinstance(target, int):
        return target

    target = clean_spaces(target)

    # A leading `-` is a sign: the phone cleanup below would drop it.
    if target.startswith("-"):
        if target[1:].isdecimal():
            return int(target)
    elif (phone := re.sub(r"[+()\s-]", "", target)).isdecimal():
        return int(phone)

    kind, value = _classify_tg_target(target)

    if kind == "invite":
        return value

    if kind == "private":
        # The capture starts with the id's digits; a `/5`, `?single` or other tail follows them.
        return get_channel_id(int(re.split(r"\D", value, maxsplit=1)[0]))

    if kind == "text":
        return re.sub(r"[@+\s]", "", value.lower())

    try:
        return get_channel_id(int(value))
    except ValueError:
        return value


@_optional_import("tg")
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


@_optional_import("tg")
def mention_tg_user(
    user_id: int, user_full_name: str | None = None, parse_mode: ParseMode | None = None
) -> str:
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
)
