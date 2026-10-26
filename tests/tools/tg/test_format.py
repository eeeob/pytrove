from __future__ import annotations as _annotations

import importlib.util
from typing import TYPE_CHECKING

import pytest

from pytrove import parse_tg_target
from pytrove.errors import ValidationError
from pytrove.tg_tools import (
    extract_pyro_update_text,
    format_hidden_tg_link,
    format_tg_link,
    format_tg_username,
    mention_tg_user,
)
from pytrove.tg_tools._internal import links

if TYPE_CHECKING:
    from collections.abc import Callable

HAS_TG = importlib.util.find_spec("pyrogram") is not None

if HAS_TG:
    from pyrogram.enums import ChatType, ParseMode
    from pyrogram.types import CallbackQuery, Chat, Message, User

needs_tg = pytest.mark.skipif(not HAS_TG, reason="needs the tg extra (kurigram)")
without_tg = pytest.mark.skipif(HAS_TG, reason="checks the error raised without the tg extra")


@needs_tg
def test_parse_tg_target_passes_an_int_through() -> None:
    assert parse_tg_target(123456) == 123456


@needs_tg
def test_parse_tg_target_reads_a_phone_number_as_an_int() -> None:
    assert parse_tg_target("+967 (777) 123-456") == 967777123456
    assert parse_tg_target("967777123456") == 967777123456


@needs_tg
def test_parse_tg_target_strips_at_and_plus_from_a_username() -> None:
    assert parse_tg_target("@some_user") == "some_user"
    assert parse_tg_target("some_user") == "some_user"


@needs_tg
def test_parse_tg_target_lowercases_a_username() -> None:
    assert parse_tg_target("@Some_User") == "some_user"


@needs_tg
def test_parse_tg_target_reads_a_channel_message_link_into_a_chat_id() -> None:
    # get_channel_id(1234567890) == -1001234567890
    assert parse_tg_target("https://t.me/c/1234567890") == -1001234567890


@needs_tg
def test_parse_tg_target_keeps_a_non_numeric_link_capture_as_a_string() -> None:
    assert parse_tg_target("https://t.me/some_channel") == "some_channel"


@needs_tg
def test_extract_pyro_update_text() -> None:
    assert extract_pyro_update_text(Message(id=1, text="hi")) == "hi"
    assert extract_pyro_update_text(Message(id=1, caption="cap")) == "cap"
    assert extract_pyro_update_text(Message(id=1)) == ""
    assert (
        extract_pyro_update_text(
            CallbackQuery(id="1", from_user=User(id=1), chat_instance="c", data="d")
        )
        == "d"
    )

    with pytest.raises(ValidationError):
        extract_pyro_update_text("text")


@needs_tg
def test_format_tg_username() -> None:
    assert format_tg_username("https://t.me/Name") == "@name"
    assert format_tg_username("@name", with_at=False) == "name"
    assert format_tg_username(User(id=1, username="u")) == "@u"
    assert format_tg_username(User(id=1)) is None
    assert format_tg_username("https://t.me/+abc", default="x") == "x"
    assert format_tg_username("https://t.me/+abc", with_invite_link=True) == "https://t.me/+abc"


@needs_tg
def test_format_tg_link() -> None:
    assert format_tg_link("@name") == "https://t.me/name"
    assert format_tg_link(123456789) == "tg://openmessage?user_id=123456789"
    assert format_tg_link(-1001234567890) == "tg://openmessage?chat_id=1234567890"
    assert format_tg_link("https://t.me/+abc") == "https://t.me/+abc"
    assert format_tg_link(Chat(id=5, username="grp")) == "https://t.me/grp"
    assert format_tg_link(Chat(id=5, invite_link="https://t.me/+abc")) == "https://t.me/+abc"
    assert format_tg_link(User(id=123456789)) == "tg://openmessage?user_id=123456789"
    assert format_tg_link("", default="none") == "none"


@needs_tg
def test_hidden_link_and_mention() -> None:
    short = format_hidden_tg_link("https://x.y", "ab")
    assert links._HIDDEN_PADDING in short
    assert links._HIDDEN_PADDING not in format_hidden_tg_link(
        "https://x.y", "long text", ParseMode.MARKDOWN
    )
    assert "tg://user?id=7" in mention_tg_user(7)
    assert "Deleted Account" in mention_tg_user(7)


@needs_tg
def test_parse_tg_target_keeps_an_invite_link_as_it_is() -> None:
    assert parse_tg_target("https://t.me/+AbC-d") == "https://t.me/+AbC-d"


@needs_tg
def test_parse_tg_target_squeezes_spaces_out_of_a_username() -> None:
    assert parse_tg_target("  Some  User ") == "someuser"


@needs_tg
def test_parse_tg_target_reads_any_telegram_domain() -> None:
    assert parse_tg_target("telegram.me/Some") == "some"
    assert parse_tg_target("www.telegram.dog/c/123/4") == -1000000000123


@needs_tg
def test_extract_pyro_update_text_of_a_callback_without_data_is_empty() -> None:
    assert (
        extract_pyro_update_text(CallbackQuery(id="1", from_user=User(id=1), chat_instance="c"))
        == ""
    )


@needs_tg
def test_extract_pyro_update_text_prefers_text_over_caption() -> None:
    assert extract_pyro_update_text(Message(id=1, text="t", caption="c")) == "t"


@needs_tg
def test_extract_pyro_update_text_names_the_refused_type() -> None:
    with pytest.raises(ValidationError, match="int"):
        extract_pyro_update_text(5)


@needs_tg
def test_format_tg_username_keeps_the_case_of_a_bare_username() -> None:
    assert format_tg_username("@Name") == "@Name"
    assert format_tg_username("  @n ") == "@n"


@needs_tg
def test_format_tg_username_of_a_chat_and_of_nothing() -> None:
    assert format_tg_username(Chat(id=1, username="Grp")) == "@Grp"
    assert format_tg_username("") is None
    assert format_tg_username(Chat(id=1), default="none") == "none"


@needs_tg
def test_format_tg_username_reads_other_telegram_domains() -> None:
    assert format_tg_username("telegram.dog/x", with_at=False) == "x"


@needs_tg
def test_format_tg_link_of_a_message_is_its_own_link() -> None:
    chat = Chat(id=-1001234567890, type=ChatType.SUPERGROUP, username="grp")

    assert format_tg_link(Message(id=7, chat=chat)) == "https://t.me/grp/7"


@needs_tg
def test_format_tg_link_of_a_public_link_is_the_canonical_t_me_link() -> None:
    assert format_tg_link("telegram.dog/x") == "https://t.me/x"
    assert format_tg_link("  @n ") == "https://t.me/n"


@needs_tg
def test_format_tg_link_of_a_numeric_string_is_read_as_an_id() -> None:
    assert format_tg_link("-1001234567890") == "tg://openmessage?chat_id=1234567890"


@needs_tg
def test_format_tg_link_of_a_zero_id_is_the_default() -> None:
    assert format_tg_link(0) is None
    assert format_tg_link(0, "none") == "none"


@needs_tg
def test_format_hidden_tg_link_pads_text_up_to_the_threshold_only() -> None:
    assert links._HIDDEN_PADDING in format_hidden_tg_link("https://x.y", "abc")
    assert format_hidden_tg_link("https://x.y", "abcd") == "<a href=https://x.y>abcd</a>"
    assert format_hidden_tg_link("https://x.y", "abcd", ParseMode.MARKDOWN) == "[abcd](https://x.y)"


@needs_tg
def test_mention_tg_user_shows_the_given_name_in_the_given_mode() -> None:
    assert mention_tg_user(7, "Ali Hassan") == "<a href=tg://user?id=7>Ali Hassan</a>"
    assert mention_tg_user(7, "Ali Hassan", ParseMode.MARKDOWN) == "[Ali Hassan](tg://user?id=7)"


JOINCHAT_LINK = "https://t.me/joinchat/AbC-d"


@needs_tg
def test_format_tg_username_treats_a_joinchat_link_as_an_invite_link() -> None:
    assert format_tg_username(JOINCHAT_LINK) is None
    assert format_tg_username(JOINCHAT_LINK, with_invite_link=True) == JOINCHAT_LINK


@needs_tg
def test_format_tg_link_returns_a_joinchat_link_as_it_is() -> None:
    assert format_tg_link(JOINCHAT_LINK) == JOINCHAT_LINK


@needs_tg
def test_parse_tg_target_keeps_a_joinchat_link_as_it_is() -> None:
    assert parse_tg_target(JOINCHAT_LINK) == JOINCHAT_LINK


@without_tg
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (extract_pyro_update_text, ("text",)),
        (format_tg_username, ("@name",)),
        (format_tg_link, ("@name",)),
        (parse_tg_target, ("@name",)),
        (format_hidden_tg_link, ("https://x.y", "ab")),
        (mention_tg_user, (7,)),
    ],
)
def test_tools_without_the_tg_extra_raise_a_clear_import_error(
    tool: Callable[..., object], args: tuple[object, ...]
) -> None:
    with pytest.raises(ImportError, match=r"pip install 'pytrove\[tg\]'"):
        tool(*args)


@needs_tg
def test_format_tg_link_of_a_private_chat_message_is_the_default() -> None:
    message = Message(id=7, chat=Chat(id=5, type=ChatType.PRIVATE))

    assert message.link == ""
    assert format_tg_link(message) is None
    assert format_tg_link(message, "none") == "none"


@needs_tg
def test_format_tg_link_keeps_a_private_channel_link_as_a_channel_link() -> None:
    assert format_tg_link("https://t.me/c/1234567890/5") == "https://t.me/c/1234567890/5"
    assert format_tg_link("telegram.dog/c/1234567890") == "https://t.me/c/1234567890"
    assert format_tg_link("https://t.me/c/1234567890/5") != format_tg_link(1234567890)


@needs_tg
def test_format_tg_link_ignores_surrounding_whitespace() -> None:
    assert format_tg_link(" https://t.me/c/1234567890/5 ") == "https://t.me/c/1234567890/5"
    assert format_tg_link(" https://t.me/+AbCdEf ") == "https://t.me/+AbCdEf"
    assert format_tg_link(" name ") == "https://t.me/name"


@needs_tg
def test_format_tg_username_of_a_private_channel_link_is_the_default() -> None:
    assert format_tg_username("https://t.me/c/1234567890/5") is None
    assert format_tg_username("T.ME/C/1234567890", default="none") == "none"
