"""`pytrove.constants.patterns`: each compiled pattern matches exactly its documented shape."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

import pytest

from pytrove.constants import patterns
from pytrove.constants.patterns import (
    EMAIL_PATTERN,
    TG_BOT_COMMAND_PATTERN,
    TG_CHANNEL_MESSAGE_LINK_PATTERN,
    TG_CHAT_LINK_PATTERN,
    TG_INVITE_LINK_PATTERN,
)

if TYPE_CHECKING:
    import re


def test_email_pattern_is_anchored() -> None:
    assert EMAIL_PATTERN.fullmatch("a@b.cd")
    assert not EMAIL_PATTERN.match("x a@b.cd")
    assert not EMAIL_PATTERN.match("a@b.c")


def test_tg_bot_command_pattern_needs_a_letter_after_the_slash() -> None:
    assert TG_BOT_COMMAND_PATTERN.match("/go_2")
    assert not TG_BOT_COMMAND_PATTERN.match("/")
    assert not TG_BOT_COMMAND_PATTERN.match("/2go")


def test_tg_bot_command_pattern_takes_a_bot_name_and_only_ascii() -> None:
    assert TG_BOT_COMMAND_PATTERN.match("/start@my_bot")
    assert not TG_BOT_COMMAND_PATTERN.match("/start@")
    assert not TG_BOT_COMMAND_PATTERN.match("/start@my bot")
    assert not TG_BOT_COMMAND_PATTERN.match("/a\u00e9")
    assert not TG_BOT_COMMAND_PATTERN.match("/a\u0663")
    assert not TG_BOT_COMMAND_PATTERN.match("/start@b\u00f6t")


def test_tg_channel_message_link_pattern_captures_the_chat_and_the_message() -> None:
    assert TG_CHANNEL_MESSAGE_LINK_PATTERN.match("t.me/name/5").groups() == ("name", "5")
    assert TG_CHANNEL_MESSAGE_LINK_PATTERN.match("t.me/c/123/9/5").groups() == ("123", "5")
    assert TG_CHANNEL_MESSAGE_LINK_PATTERN.match("t.me/name") is None


def test_tg_chat_link_pattern_captures_a_name_or_an_id() -> None:
    assert TG_CHAT_LINK_PATTERN.match("t.me/name/5").group(1) == "name"
    assert TG_CHAT_LINK_PATTERN.match("https://www.telegram.me/c/123/4").group(1) == "123"
    assert TG_CHAT_LINK_PATTERN.match("https://example.com/name") is None
    assert TG_CHAT_LINK_PATTERN.match("@name") is None


def test_tg_invite_link_pattern_captures_the_hash_of_both_forms() -> None:
    assert TG_INVITE_LINK_PATTERN.match("https://t.me/+hash").group(1) == "hash"
    assert TG_INVITE_LINK_PATTERN.match("t.me/joinchat/Ab-c").group(1) == "Ab-c"
    assert TG_INVITE_LINK_PATTERN.match("https://t.me/name") is None
    assert TG_INVITE_LINK_PATTERN.match("https://t.me/+hash/5") is None


@pytest.mark.parametrize(
    ("pattern", "text"),
    [
        (EMAIL_PATTERN, "a@b.cd"),
        (TG_BOT_COMMAND_PATTERN, "/start"),
        (TG_CHANNEL_MESSAGE_LINK_PATTERN, "t.me/name/5"),
        (TG_CHAT_LINK_PATTERN, "t.me/name"),
        (TG_INVITE_LINK_PATTERN, "t.me/+hash"),
    ],
)
def test_every_pattern_rejects_a_trailing_newline(pattern: re.Pattern[str], text: str) -> None:
    assert pattern.match(text)
    assert pattern.match(text + "\n") is None


@pytest.mark.parametrize("host", ["t.me", "telegram.me", "telegram.dog", "telegram.org"])
def test_the_link_patterns_take_each_telegram_host(host: str) -> None:
    assert TG_CHANNEL_MESSAGE_LINK_PATTERN.match(f"https://{host}/name/5")
    assert TG_CHAT_LINK_PATTERN.match(f"https://www.{host}/name")
    assert TG_INVITE_LINK_PATTERN.match(f"{host}/+hash")


@pytest.mark.parametrize("host", ["t.org", "t.dog", "tme", "t.me.evil.com"])
def test_the_link_patterns_refuse_other_hosts(host: str) -> None:
    assert TG_CHANNEL_MESSAGE_LINK_PATTERN.match(f"https://{host}/name/5") is None
    assert TG_CHAT_LINK_PATTERN.match(f"https://{host}/name") is None
    assert TG_INVITE_LINK_PATTERN.match(f"{host}/+hash") is None


@pytest.mark.parametrize("link", ["t.me/name/5", "t.me/name/5/", "t.me/c/123/5/"])
def test_the_message_link_pattern_takes_an_optional_trailing_slash(link: str) -> None:
    match = TG_CHANNEL_MESSAGE_LINK_PATTERN.match(link)

    assert match is not None
    assert match.group(2) == "5"


def test_all_lists_exactly_the_patterns() -> None:
    assert patterns.__all__ == (
        "EMAIL_PATTERN",
        "TG_BOT_COMMAND_PATTERN",
        "TG_CHANNEL_MESSAGE_LINK_PATTERN",
        "TG_CHAT_LINK_PATTERN",
        "TG_INVITE_LINK_PATTERN",
    )
