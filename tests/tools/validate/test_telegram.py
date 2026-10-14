from __future__ import annotations as _annotations

from typing import Any

import pytest
from pyrogram.types import Message

from pytrove.validate_tools import telegram
from pytrove.validate_tools.telegram import (
    is_tg_bot_command,
    is_tg_bot_token,
    is_tg_channel_id,
    is_tg_channel_message_link,
    is_tg_otp_code,
    is_tg_user_id,
    is_valid_tg_app,
    TG_BOT_COMMAND_PATTERN,
    TG_CHANNEL_MSG_LINK_PATTERN,
)


@pytest.mark.parametrize(("value", "channel", "user"), [
    (-1001234567890, True, False),
    (123456789, False, True),
    (-123456789, False, False),
    (0, False, False),
    ("123", False, False),
])
def test_peer_id_checks(value: Any, channel: bool, user: bool) -> None:
    assert is_tg_channel_id(value) is channel
    assert is_tg_user_id(value) is user


@pytest.mark.parametrize(("token", "expected"), [
    ("123456:ABC-def", True),
    ("abc:def", False),
    ("123456", False),
    ("1:2:3", False),
    (123456, False),
])
def test_is_tg_bot_token(token: Any, expected: bool) -> None:
    assert is_tg_bot_token(token) is expected


@pytest.mark.parametrize(("text", "expected"), [
    ("/start", True),
    ("/set_name2", True),
    ("/2fa", False),
    ("start", False),
    ("/start now", False),
    ("", False),
])
def test_is_tg_bot_command_on_text(text: str, expected: bool) -> None:
    assert is_tg_bot_command(text) is expected


def test_is_tg_bot_command_reads_a_messages_text() -> None:
    assert is_tg_bot_command(Message(id=1, text="/help"))
    assert not is_tg_bot_command(Message(id=1))


@pytest.mark.parametrize(("link", "expected"), [
    ("https://t.me/channel/42", True),
    ("t.me/c/1234567/42", True),
    ("HTTPS://TELEGRAM.ME/Channel/7/", True),
    ("https://t.me/channel", False),
    ("https://example.com/channel/42", False),
    (42, False),
])
def test_is_tg_channel_message_link(link: Any, expected: bool) -> None:
    assert is_tg_channel_message_link(link) is expected


def test_the_patterns_match_their_documented_shapes() -> None:
    assert TG_CHANNEL_MSG_LINK_PATTERN.match("t.me/name/5").groups() == ("name", "5")
    assert TG_BOT_COMMAND_PATTERN.match("/go")
    assert not TG_BOT_COMMAND_PATTERN.match("/")


@pytest.mark.parametrize(("code", "kwargs", "expected"), [
    (12345, {}, True),
    (1234, {}, False),
    ("12345", {}, True),
    ("12 345", {}, False),
    ("12 345", {"remove_spaces": True}, True),
    ("1234a", {}, False),
    ("12345", {"with_str": False}, False),
    (12345.0, {}, False),
])
def test_is_tg_otp_code(code: Any, kwargs: dict[str, Any], expected: bool) -> None:
    assert is_tg_otp_code(code, **kwargs) is expected


class _FakeClient:
    """Stands in for `pyrogram.Client`; `connect` fails with whatever `error` holds."""

    error: BaseException | None = None
    disconnect_error: BaseException | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Accept and ignore the real client's arguments."""

    async def connect(self) -> None:
        """Connect, or raise `error`."""
        if self.error is not None:
            raise self.error

    async def disconnect(self) -> None:
        """Disconnect, or raise `disconnect_error`."""
        if self.disconnect_error is not None:
            raise self.disconnect_error


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> type[_FakeClient]:
    """Replace the Telegram client with `_FakeClient`, reset for each test."""
    monkeypatch.setattr(_FakeClient, "error", None)
    monkeypatch.setattr(_FakeClient, "disconnect_error", None)
    monkeypatch.setattr(telegram, "Client", _FakeClient)
    return _FakeClient


async def test_is_valid_tg_app_is_true_when_telegram_accepts(fake_client: type[_FakeClient]) -> None:
    assert await is_valid_tg_app("12345", "hash") is True


async def test_is_valid_tg_app_is_false_on_bad_request(fake_client: type[_FakeClient]) -> None:
    fake_client.error = telegram.BadRequest()
    assert await is_valid_tg_app(12345, "hash") is False


async def test_is_valid_tg_app_is_false_for_a_non_numeric_id(fake_client: type[_FakeClient]) -> None:
    assert await is_valid_tg_app("abc", "hash") is False


async def test_is_valid_tg_app_lets_other_failures_propagate(fake_client: type[_FakeClient]) -> None:
    fake_client.error = ConnectionError()

    with pytest.raises(ConnectionError):
        await is_valid_tg_app(1, "hash")


async def test_is_valid_tg_app_logs_a_failed_disconnect(
    fake_client: type[_FakeClient], caplog: pytest.LogCaptureFixture,
) -> None:
    fake_client.disconnect_error = OSError()
    assert await is_valid_tg_app(1, "hash") is True
    assert "Failed to disconnect" in caplog.text
