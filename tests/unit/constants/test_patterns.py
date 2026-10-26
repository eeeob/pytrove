"""`pytrove.constants.patterns`: each compiled pattern matches exactly its documented shape."""

from __future__ import annotations as _annotations

from pytrove.constants import patterns
from pytrove.constants.patterns import (
    EMAIL_PATTERN,
    TG_BOT_COMMAND_PATTERN,
    TG_CHANNEL_MESSAGE_LINK_PATTERN,
    TG_CHAT_LINK_PATTERN,
    TG_INVITE_LINK_PATTERN,
)


def test_email_pattern_is_anchored() -> None:
    assert EMAIL_PATTERN.fullmatch("a@b.cd")
    assert not EMAIL_PATTERN.match("x a@b.cd")
    assert not EMAIL_PATTERN.match("a@b.c")


def test_tg_bot_command_pattern_needs_a_letter_after_the_slash() -> None:
    assert TG_BOT_COMMAND_PATTERN.match("/go_2")
    assert not TG_BOT_COMMAND_PATTERN.match("/")
    assert not TG_BOT_COMMAND_PATTERN.match("/2go")


def test_tg_channel_message_link_pattern_captures_the_chat_and_the_message() -> None:
    assert TG_CHANNEL_MESSAGE_LINK_PATTERN.match("t.me/name/5").groups() == ("name", "5")
    assert TG_CHANNEL_MESSAGE_LINK_PATTERN.match("t.me/c/123/9/5").groups() == ("123", "5")
    assert TG_CHANNEL_MESSAGE_LINK_PATTERN.match("t.me/name") is None


def test_tg_chat_link_pattern_captures_a_name_or_an_id() -> None:
    assert TG_CHAT_LINK_PATTERN.match("t.me/name/5").group(1) == "name"
    assert TG_CHAT_LINK_PATTERN.match("https://www.telegram.org/c/123/4").group(1) == "123"
    assert TG_CHAT_LINK_PATTERN.match("https://example.com/name") is None
    assert TG_CHAT_LINK_PATTERN.match("@name") is None


def test_tg_invite_link_pattern_captures_the_hash_of_both_forms() -> None:
    assert TG_INVITE_LINK_PATTERN.match("https://t.me/+hash").group(1) == "hash"
    assert TG_INVITE_LINK_PATTERN.match("t.me/joinchat/Ab-c").group(1) == "Ab-c"
    assert TG_INVITE_LINK_PATTERN.match("https://t.me/name") is None
    assert TG_INVITE_LINK_PATTERN.match("https://t.me/+hash/5") is None


def test_all_lists_exactly_the_patterns() -> None:
    assert patterns.__all__ == (
        "EMAIL_PATTERN",
        "TG_BOT_COMMAND_PATTERN",
        "TG_CHANNEL_MESSAGE_LINK_PATTERN",
        "TG_CHAT_LINK_PATTERN",
        "TG_INVITE_LINK_PATTERN",
    )
