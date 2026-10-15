from pytrove import parse_tg_target
import pytest
from pytrove import (
    rand_tg_device,
)
from pytrove.enums import PlatformDevice
from pytrove.tg_tools import fetch_tg_email_code


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


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_rand_tg_device_works_for_every_platform(platform):
    device = rand_tg_device(platform)
    assert device.model and device.version


async def test_fetch_tg_email_code_matches_a_six_digit_code(monkeypatch):
    async def fake_fetch(*args, **kwargs):
        yield "Hello Ali Hassan, your code is 123456"

    monkeypatch.setattr("pytrove.tg_tools.accounts.fetch_emails_from", fake_fetch)
    monkeypatch.setattr(
        "pytrove.tg_tools.accounts.detect_email_provider",
        lambda email: None,
    )

    assert await fetch_tg_email_code("a@gmail.com", "pw", "Ali Hassan", 6) == "123456"
