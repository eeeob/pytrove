"""Checks for Telegram identifiers, links, commands and credentials."""

from __future__ import annotations as _annotations

import logging
from typing import TYPE_CHECKING, Any, Final, TypeGuard, overload

try:
    from pyrogram import Client  # type: ignore[import-not-found]  # Optional: the `tg` extra.
    from pyrogram.errors import BadRequest  # type: ignore[import-not-found]  # Optional: the `tg` extra.
    from pyrogram.utils import get_peer_type  # type: ignore[import-not-found]  # Optional: the `tg` extra.
except ImportError:
    pass

from .._internal import _optional_import
from ..constants import TG_BOT_COMMAND_PATTERN, TG_CHANNEL_MESSAGE_LINK_PATTERN

if TYPE_CHECKING:
    from pyrogram.types import Message  # type: ignore[import-not-found]  # Optional: the `tg` extra.

    from ..typings import StrInt, _False, _True

_OTP_LENGTH: Final[int] = 5
"""Digits in a Telegram login code."""

log = logging.getLogger(__name__)


@_optional_import("tg")
def is_tg_channel_id(value: Any) -> TypeGuard[int]:
    """Tell whether `value` is a channel or supergroup id (`-100...`).

    Args:
        value: The value to test.

    Returns:
        Whether it is an int, not a `bool`, that Pyrogram reads as a channel peer.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        return False

    try:
        return get_peer_type(value) == "channel"
    except ValueError:
        return False


@_optional_import("tg")
def is_tg_user_id(value: Any) -> TypeGuard[int]:
    """Tell whether `value` is a user id.

    Args:
        value: The value to test.

    Returns:
        Whether it is an int, not a `bool`, that Pyrogram reads as a user peer.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        return False

    try:
        return get_peer_type(value) == "user"
    except ValueError:
        return False


def is_tg_bot_token(bot_token: Any) -> TypeGuard[str]:
    """Tell whether `bot_token` has the shape of a bot token: `<digits>:<secret>`.

    Args:
        bot_token: The value to test.

    Returns:
        Whether it is a string of exactly two `:`-separated parts, the first ASCII
        digits and the second not empty.

    Example:
        >>> is_tg_bot_token("123456:ABC-def")
        True
        >>> is_tg_bot_token("abc:def")
        False
    """
    if not isinstance(bot_token, str):
        return False

    bot_id, sep, secret = bot_token.partition(":")
    return bool(sep and secret and ":" not in secret and bot_id.isascii() and bot_id.isdigit())


def is_tg_bot_command(message: Message | str) -> bool:
    """Tell whether a message, or its text, is exactly one bot command.

    The command may carry the `@botname` suffix Telegram adds in groups
    (`/start@my_bot`); arguments after it, or a trailing newline, make it false.
    A plain `str` needs no extra; a message is read through its `text`, so a
    message with only a caption is false.

    Args:
        message: A Pyrogram `Message` or its text.

    Returns:
        Whether the text matches `TG_BOT_COMMAND_PATTERN`.

    Example:
        >>> is_tg_bot_command("/start@my_bot")
        True
        >>> is_tg_bot_command("/start now")
        False
    """
    text = getattr(message, "text", message)
    return isinstance(text, str) and bool(TG_BOT_COMMAND_PATTERN.match(text))


def is_tg_channel_message_link(message_link: Any) -> TypeGuard[str]:
    """Tell whether `message_link` links to a message in a channel, in any letter case.

    Args:
        message_link: The value to test.

    Returns:
        Whether it is a string matching `TG_CHANNEL_MESSAGE_LINK_PATTERN`.

    Example:
        >>> is_tg_channel_message_link("https://t.me/durov/5")
        True
        >>> is_tg_channel_message_link("t.me/c/123456/7")
        True
        >>> is_tg_channel_message_link("https://t.me/durov")
        False
    """
    return isinstance(message_link, str) and bool(
        TG_CHANNEL_MESSAGE_LINK_PATTERN.match(message_link.lower())
    )


@overload
def is_tg_otp_code(
    code: Any, allow_str: _True = True, remove_spaces: bool = False
) -> TypeGuard[StrInt]: ...
@overload
def is_tg_otp_code(code: Any, allow_str: _False, remove_spaces: bool = False) -> TypeGuard[int]: ...
@overload
def is_tg_otp_code(
    code: Any, allow_str: bool = True, remove_spaces: bool = False
) -> TypeGuard[StrInt]: ...
def is_tg_otp_code(code: Any, allow_str: bool = True, remove_spaces: bool = False) -> bool:
    """Tell whether `code` looks like a five-digit Telegram login code.

    Args:
        code: The value to test.
        allow_str: Whether a numeric string counts as well as an int.
        remove_spaces: Whether to strip whitespace from a string first.

    Returns:
        Whether it is a five-digit int (`10000` to `99999`, never a `bool`), or
        (with `allow_str`) a string of exactly five ASCII digits.

    Example:
        >>> is_tg_otp_code(12345)
        True
        >>> is_tg_otp_code("1 2 3 4 5", remove_spaces=True)
        True
        >>> is_tg_otp_code("12345", allow_str=False)
        False
    """
    if isinstance(code, int):
        return not isinstance(code, bool) and 10 ** (_OTP_LENGTH - 1) <= code < 10**_OTP_LENGTH

    if isinstance(code, str) and allow_str:
        if remove_spaces:
            from ..text_tools import clean_spaces  # noqa: PLC0415 - `text_tools` sits above `validate_tools` in the import layering

            code = clean_spaces(code)

        return len(code) == _OTP_LENGTH and code.isascii() and code.isdigit()

    return False


@_optional_import("tg")
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

    c = Client(
        f"check_session_{api_id}", api_id=api_id, api_hash=api_hash, in_memory=True, no_updates=True
    )

    try:
        await c.connect()
    except BadRequest:
        return False
    else:
        return True
    finally:
        try:
            # `connect` marks the client connected only once the session is up, and `disconnect`
            # refuses a client that is not, so a rejected pair closes only the storage it opened.
            if c.is_connected:
                await c.disconnect()
            else:
                await c.storage.close()
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
)
