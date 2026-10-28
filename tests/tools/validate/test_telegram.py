from __future__ import annotations as _annotations

import logging
from typing import Any

import pytest

from pytrove.validate_tools import telegram
from pytrove.validate_tools.telegram import (
    _OTP_LENGTH,
    is_tg_bot_command,
    is_tg_bot_token,
    is_tg_channel_id,
    is_tg_channel_message_link,
    is_tg_otp_code,
    is_tg_user_id,
    is_valid_tg_app,
)

from pytrove.models.template_models.template import HAS_PYROGRAM

needs_pyrogram = pytest.mark.skipif(not HAS_PYROGRAM, reason="needs the tg extra")


@needs_pyrogram
@pytest.mark.parametrize(
    ("value", "channel", "user"),
    [
        (-1001234567890, True, False),
        (123456789, False, True),
        (-123456789, False, False),
        (0, False, False),
        ("123", False, False),
        (True, False, False),
        (False, False, False),
        (2**70, False, False),
    ],
)
def test_peer_id_checks(value: Any, channel: bool, user: bool) -> None:
    assert is_tg_channel_id(value) is channel
    assert is_tg_user_id(value) is user


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("123456:ABC-def", True),
        ("123456:ABC", True),
        ("abc:def", False),
        ("123456", False),
        ("1:2:3", False),
        (123456, False),
        ("123456:", False),
        (":ABC", False),
        ("\u0661\u0662\u0663:abc", False),
        ("\u00b2:abc", False),
    ],
)
def test_is_tg_bot_token(token: Any, expected: bool) -> None:
    assert is_tg_bot_token(token) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/Start", True),
        ("/start", True),
        ("/set_name2", True),
        ("/2fa", False),
        ("start", False),
        ("/start now", False),
        ("/start\n", False),
        ("/start@my_bot", True),
        ("/start@my_bot now", False),
        ("/\u0645\u0631\u062d\u0628\u0627", False),
        ("", False),
        (None, False),
    ],
)
def test_is_tg_bot_command_on_text_needs_no_extra(text: Any, expected: bool) -> None:
    assert is_tg_bot_command(text) is expected


@needs_pyrogram
def test_is_tg_bot_command_reads_a_messages_text() -> None:
    message = pytest.importorskip("pyrogram.types").Message
    assert is_tg_bot_command(message(id=1, text="/help"))
    assert not is_tg_bot_command(message(id=1))
    assert not is_tg_bot_command(message(id=1, caption="/help"))


@pytest.mark.skipif(HAS_PYROGRAM, reason="the tg extra is installed")
async def test_the_pyrogram_checks_name_the_tg_extra_when_it_is_missing() -> None:
    for check in (is_tg_channel_id, is_tg_user_id):
        with pytest.raises(ImportError, match=r"pytrove\[tg\]"):
            check(1)

    with pytest.raises(ImportError, match=r"pytrove\[tg\]"):
        await is_valid_tg_app(1, "hash")


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        ("https://t.me/channel/42", True),
        ("t.me/c/1234567/42", True),
        ("HTTPS://TELEGRAM.ME/Channel/7/", True),
        ("https://t.me/channel", False),
        ("t.me/channel/42\n", False),
        ("https://telegram.dog/channel/42", True),
        ("https://telegram.org/channel/42/", True),
        ("https://t.org/channel/42", False),
        ("https://example.com/channel/42", False),
        (42, False),
        ("t.me/c/1/2/3", True),
        ("https://www.t.me/channel/42", True),
        ("telegram.dog/channel/42\n", False),
    ],
)
def test_is_tg_channel_message_link(link: Any, expected: bool) -> None:
    assert is_tg_channel_message_link(link) is expected


@pytest.mark.parametrize(
    ("code", "kwargs", "expected"),
    [
        (12345, {}, True),
        (1234, {}, False),
        ("12345", {}, True),
        ("12 345", {}, False),
        ("12 345", {"remove_spaces": True}, True),
        ("1234a", {}, False),
        ("12345", {"allow_str": False}, False),
        (12345, {"allow_str": False}, True),
        (12345.0, {}, False),
        (10000, {}, True),
        (99999, {}, True),
        (100000, {}, False),
        (-1234, {}, False),
        (-12345, {}, False),
        (True, {}, False),
        ("01234", {}, True),
        (" 1234", {}, False),
        ("1234 ", {}, False),
        ("1_234", {}, False),
        ("+1234", {}, False),
        ("\u0661\u0662\u0663\u0664\u0665", {}, False),
        ("12\u00b245", {}, False),
        ("123456", {}, False),
    ],
)
def test_is_tg_otp_code(code: Any, kwargs: dict[str, Any], expected: bool) -> None:
    assert is_tg_otp_code(code, **kwargs) is expected


def test_otp_length_is_five() -> None:
    assert _OTP_LENGTH == 5


class _FakeStorage:
    """Records whether it was closed."""

    closed = False

    async def close(self) -> None:
        """Record the close."""
        self.closed = True


class _FakeClient:
    """Stands in for `pyrogram.Client`; `connect` fails with whatever `error` holds.

    Like the real one, it counts as connected only once `connect` succeeds, and
    `disconnect` refuses a client that is not.
    """

    error: BaseException | None = None
    disconnect_error: BaseException | None = None
    instances: list[_FakeClient] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Accept and ignore the real client's arguments."""
        self.is_connected: bool | None = None
        self.storage = _FakeStorage()
        _FakeClient.instances.append(self)

    async def connect(self) -> None:
        """Connect, or raise `error`."""
        if self.error is not None:
            raise self.error

        self.is_connected = True

    async def disconnect(self) -> None:
        """Disconnect, or raise `disconnect_error`."""
        if not self.is_connected:
            msg = "Client is already disconnected"
            raise ConnectionError(msg)

        if self.disconnect_error is not None:
            raise self.disconnect_error

        await self.storage.close()
        self.is_connected = False


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> type[_FakeClient]:
    """Replace the Telegram client with `_FakeClient`, reset for each test."""
    monkeypatch.setattr(_FakeClient, "error", None)
    monkeypatch.setattr(_FakeClient, "disconnect_error", None)
    monkeypatch.setattr(_FakeClient, "instances", [])
    monkeypatch.setattr(telegram, "Client", _FakeClient)
    return _FakeClient


@needs_pyrogram
async def test_is_valid_tg_app_is_true_when_telegram_accepts(
    fake_client: type[_FakeClient],
) -> None:
    assert await is_valid_tg_app("12345", "hash") is True
    assert fake_client.instances[0].is_connected is False
    assert fake_client.instances[0].storage.closed


@needs_pyrogram
async def test_is_valid_tg_app_is_false_on_bad_request(
    fake_client: type[_FakeClient],
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_client.error = telegram.BadRequest()

    with caplog.at_level(logging.ERROR):
        assert await is_valid_tg_app(12345, "hash") is False

    assert fake_client.instances[0].storage.closed
    assert caplog.records == []


@needs_pyrogram
async def test_is_valid_tg_app_is_false_for_a_non_numeric_id(
    fake_client: type[_FakeClient],
) -> None:
    assert await is_valid_tg_app("abc", "hash") is False


@needs_pyrogram
async def test_is_valid_tg_app_lets_other_failures_propagate(
    fake_client: type[_FakeClient],
) -> None:
    fake_client.error = ConnectionError()

    with pytest.raises(ConnectionError):
        await is_valid_tg_app(1, "hash")


@needs_pyrogram
async def test_is_valid_tg_app_logs_a_failed_disconnect(
    fake_client: type[_FakeClient],
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_client.disconnect_error = OSError()
    assert await is_valid_tg_app(1, "hash") is True
    assert "Failed to disconnect" in caplog.text
