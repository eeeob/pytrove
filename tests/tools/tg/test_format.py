from __future__ import annotations as _annotations

import pytest
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Chat, Message, User

from pytrove import parse_tg_target
from pytrove.errors import ValidationError
from pytrove.tg_tools import (
    extract_pyro_update_text,
    format_hidden_tg_link,
    format_tg_link,
    format_tg_username,
    mention_tg_user,
    CHAT_LINK_PATTERN,
    INVITE_LINK_PATTERN,
)
from pytrove.tg_tools._internal import links


def test_parse_tg_target_passes_an_int_through():
    assert parse_tg_target(123456) == 123456


def test_parse_tg_target_reads_a_phone_number_as_an_int():
    assert parse_tg_target("+967 (777) 123-456") == 967777123456
    assert parse_tg_target("967777123456") == 967777123456


def test_parse_tg_target_strips_at_and_plus_from_a_username():
    assert parse_tg_target("@some_user") == "some_user"
    assert parse_tg_target("some_user") == "some_user"


def test_parse_tg_target_lowercases_a_username():
    assert parse_tg_target("@Some_User") == "some_user"


def test_parse_tg_target_reads_a_channel_message_link_into_a_chat_id():
    # get_channel_id(1234567890) == -1001234567890
    assert parse_tg_target("https://t.me/c/1234567890") == -1001234567890


def test_parse_tg_target_keeps_a_non_numeric_link_capture_as_a_string():
    assert parse_tg_target("https://t.me/some_channel") == "some_channel"


def test_extract_pyro_update_text() -> None:
    assert extract_pyro_update_text(Message(id=1, text="hi")) == "hi"
    assert extract_pyro_update_text(Message(id=1, caption="cap")) == "cap"
    assert extract_pyro_update_text(Message(id=1)) == ""
    assert extract_pyro_update_text(CallbackQuery(id="1", from_user=User(id=1), chat_instance="c", data="d")) == "d"

    with pytest.raises(ValidationError):
        extract_pyro_update_text("text")


def test_format_tg_username() -> None:
    assert format_tg_username("https://t.me/Name") == "@name"
    assert format_tg_username("@name", with_at=False) == "name"
    assert format_tg_username(User(id=1, username="u")) == "@u"
    assert format_tg_username(User(id=1)) is None
    assert format_tg_username("https://t.me/+abc", default="x") == "x"
    assert format_tg_username("https://t.me/+abc", with_invite_link=True) == "https://t.me/+abc"


def test_format_tg_link() -> None:
    assert format_tg_link("@name") == "https://t.me/name"
    assert format_tg_link(123456789) == "tg://openmessage?user_id=123456789"
    assert format_tg_link(-1001234567890) == "tg://openmessage?chat_id=1234567890"
    assert format_tg_link("https://t.me/+abc") == "https://t.me/+abc"
    assert format_tg_link(Chat(id=5, username="grp")) == "https://t.me/grp"
    assert format_tg_link(Chat(id=5, invite_link="https://t.me/+abc")) == "https://t.me/+abc"
    assert format_tg_link(User(id=123456789)) == "tg://openmessage?user_id=123456789"
    assert format_tg_link("", default="none") == "none"


def test_hidden_link_and_mention() -> None:
    short = format_hidden_tg_link("https://x.y", "ab")
    assert links._HIDDEN_PADDING in short
    assert links._HIDDEN_PADDING not in format_hidden_tg_link("https://x.y", "long text", ParseMode.MARKDOWN)
    assert "tg://user?id=7" in mention_tg_user(7)
    assert "Deleted Account" in mention_tg_user(7)


def test_link_patterns() -> None:
    assert CHAT_LINK_PATTERN.match("t.me/name/5").group(1) == "name"
    assert INVITE_LINK_PATTERN.match("https://t.me/+hash").group(1) == "hash"
