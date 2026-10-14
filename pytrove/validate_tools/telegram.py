"""Checks for Telegram identifiers, links, commands and credentials."""

from __future__ import annotations as _annotations

import logging
import re
import sys
from typing import Any, Final, overload

if sys.version_info >= (3, 13):
    from typing import TypeIs
else:
    from typing import TypeGuard as TypeIs

try:
    from pyrogram import Client
    from pyrogram.errors import BadRequest
    from pyrogram.types import Message
    from pyrogram.utils import get_peer_type
except ImportError:
    pass

from .._internal._optional import _optional_import
from ..typings import StrInt, _False, _True

TG_CHANNEL_MSG_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t(?:elegram)?\.(?:org|me|dog)/(?:c/)?)([\w]+)(?:/\d+)*/(\d+)/?$"
)
"""A link to a message in a channel, public (`t.me/name/5`) or private (`t.me/c/123/5`)."""

TG_BOT_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(r"^/[A-Za-z][\w\d]*$")
"""A bot command: a slash, a letter, then letters, digits or underscores."""

_OTP_LENGTH: Final[int] = 5
"""Digits in a Telegram login code."""

log = logging.getLogger(__name__)


@_optional_import(("kurigram", "tg"))
def is_tg_channel_id(value: Any) -> TypeIs[int]:
    """Tell whether `value` is a channel or supergroup id (`-100...`).

    Args:
        value: The value to test.

    Returns:
        Whether it is an int Pyrogram reads as a channel peer.
    """
    try:
        return isinstance(value, int) and get_peer_type(value) == "channel"
    except ValueError:
        return False


@_optional_import(("kurigram", "tg"))
def is_tg_user_id(value: Any) -> TypeIs[int]:
    """Tell whether `value` is a user id.

    Args:
        value: The value to test.

    Returns:
        Whether it is an int Pyrogram reads as a user peer.
    """
    try:
        return isinstance(value, int) and get_peer_type(value) == "user"
    except ValueError:
        return False


def is_tg_bot_token(bot_token: Any) -> TypeIs[str]:
    """Tell whether `bot_token` has the shape of a bot token: `<digits>:<secret>`.

    Args:
        bot_token: The value to test.

    Returns:
        Whether it is a string of exactly two `:`-separated parts, the first all digits.
    """
    if not isinstance(bot_token, str) or ":" not in bot_token:
        return False

    parts = bot_token.split(":")
    return len(parts) == 2 and parts[0].isdecimal()


@_optional_import(("kurigram", "tg"))
def is_tg_bot_command(message: Message | str) -> TypeIs[str]:
    """Tell whether a message, or its text, is exactly one bot command.

    Args:
        message: A Pyrogram `Message` or its text.

    Returns:
        Whether the text matches `TG_BOT_COMMAND_PATTERN`.
    """
    if isinstance(message, Message):
        message = message.text or ""

    return isinstance(message, str) and bool(message) and bool(TG_BOT_COMMAND_PATTERN.match(message))


def is_tg_channel_message_link(message_link: Any) -> TypeIs[str]:
    """Tell whether `message_link` links to a message in a channel, in any letter case.

    Args:
        message_link: The value to test.

    Returns:
        Whether it is a string matching `TG_CHANNEL_MSG_LINK_PATTERN`.
    """
    return isinstance(message_link, str) and bool(TG_CHANNEL_MSG_LINK_PATTERN.match(message_link.lower()))


@overload
def is_tg_otp_code(code: Any, with_str: _True = True, remove_spaces: bool = False) -> TypeIs[StrInt]: ...
@overload
def is_tg_otp_code(code: Any, with_str: _False) -> TypeIs[int]: ...
def is_tg_otp_code(code: Any, with_str: bool = True, remove_spaces: bool = False) -> bool:
    """Tell whether `code` looks like a five-digit Telegram login code.

    Args:
        code: The value to test.
        with_str: Whether a numeric string counts as well as an int.
        remove_spaces: Whether to strip whitespace from a string first.

    Returns:
        Whether it is a five-digit int, or (with `with_str`) a five-character numeric string.
    """
    if isinstance(code, int):
        return len(str(code)) == _OTP_LENGTH

    if isinstance(code, str) and with_str:
        if remove_spaces:
            from ..text_tools import clean_spaces

            code = clean_spaces(code)

        from ..num_tools import to_int

        return len(code) == _OTP_LENGTH and isinstance(to_int(code, False), int)

    return False


@_optional_import(("kurigram", "tg"))
async def is_valid_tg_app(api_id: StrInt, api_hash: str) -> bool:
    """Tell whether an `api_id`/`api_hash` pair works, by connecting with it.

    Only `BadRequest`, Telegram's answer for a wrong or banned pair, means
    "no". A network failure or an outage is not an answer, so it propagates.

    Args:
        api_id: The application id.
        api_hash: The application hash.

    Returns:
        Whether Telegram accepted the pair; `False` for an `api_id` that is not a number.
    """
    try:
        api_id = int(api_id)
    except (TypeError, ValueError):
        return False

    c = Client(f"check_session_{api_id}", api_id=api_id, api_hash=api_hash, in_memory=True, no_updates=True)

    try:
        await c.connect()
    except BadRequest:
        return False
    else:
        return True
    finally:
        try:
            await c.disconnect()
        except Exception as e:
            log.error("Failed to disconnect the Telegram client", exc_info=e)


__all__ = (
    "is_tg_channel_id",
    "is_tg_user_id",
    "is_tg_bot_token",
    "is_tg_bot_command",
    "is_tg_channel_message_link",
    "is_tg_otp_code",
    "is_valid_tg_app",
    "TG_CHANNEL_MSG_LINK_PATTERN",
    "TG_BOT_COMMAND_PATTERN",
)
