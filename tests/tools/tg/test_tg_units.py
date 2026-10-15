from __future__ import annotations as _annotations

import subprocess
import sys
import time

import pytest
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Chat, Message, User

from pytrove.enums import PlatformDevice
from pytrove.errors import ValidationError
from pytrove.models import DeviceInfo
from pytrove.tg_tools import (
    extract_pyro_update_text,
    format_hidden_tg_link,
    format_tg_link,
    format_tg_username,
    mention_tg_user,
    rand_tg_device,
    split_tg_message,
    tg_account_created_at,
    CHAT_LINK_PATTERN,
    INVITE_LINK_PATTERN,
)
from pytrove.tg_tools._internal import links, points
from pytrove.tg_tools._internal.families import _DEVICES, _rng, random_family

LAZY_PROBE = """
import pytrove
from pytrove.tg_tools._internal import catalog, points
assert catalog._catalog.cache_info().currsize == 0
assert points._points.cache_info().currsize == 0
pytrove.rand_tg_device(unique_id="probe")
pytrove.tg_account_created_at(1)
assert catalog._catalog.cache_info().currsize == 1
assert points._points.cache_info().currsize == 1
"""


def test_bundled_data_is_read_on_first_use_and_not_at_import() -> None:
    subprocess.run([sys.executable, "-c", LAZY_PROBE], check=True)


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
    assert format_tg_link("", default="none") == "none"


def test_hidden_link_and_mention() -> None:
    short = format_hidden_tg_link("https://x.y", "ab")
    assert links._HIDDEN_PADDING in short
    assert links._HIDDEN_PADDING not in format_hidden_tg_link("https://x.y", "long text", ParseMode.MARKDOWN)
    assert "tg://user?id=7" in mention_tg_user(7)
    assert "Deleted Account" in mention_tg_user(7)
    assert links._SHORT_LINK_TEXT == 3


def test_link_patterns() -> None:
    assert CHAT_LINK_PATTERN.match("t.me/name/5").group(1) == "name"
    assert INVITE_LINK_PATTERN.match("https://t.me/+hash").group(1) == "hash"


def test_split_tg_message_breaks_between_lines_and_cuts_long_ones() -> None:
    assert split_tg_message(" short ") == ["short"]
    # A line keeps its trailing newline while packing, so "aa\n" + "bb\n" is 6 characters.
    assert split_tg_message("aa\nbb\ncc", length=5) == ["aa", "bb\ncc"]
    assert split_tg_message("aa\nbb\ncc", length=5, reverse=True) == ["bb\ncc", "aa"]
    assert split_tg_message("abcdefgh", length=3) == ["abc", "def", "gh"]
    assert split_tg_message("abcdefgh\nx", length=3, reverse=True) == ["x", "gh", "def", "abc"]


def test_account_age_is_interpolated_and_capped() -> None:
    first_id, first_time = points._points()[0]
    assert tg_account_created_at(first_id) == first_time
    assert tg_account_created_at(0) == first_time
    assert tg_account_created_at(10**12) <= time.time()
    mid = (points._points()[1][0] + points._points()[2][0]) // 2
    assert points._points()[1][1] <= tg_account_created_at(mid) <= points._points()[2][1]


def test_interpolate_time() -> None:
    assert points._interpolate_time(5, 0, 0.0, 10, 100.0) == 50.0
    assert points._interpolate_time(5, 3, 7.0, 3, 9.0) == 7.0
    assert points._interpolate_time(10**9, 0, 0.0, 1, 10**12) <= time.time()
    assert points._POINTS_FILE.name == "tg_points.json"


def test_rand_tg_device_pins_and_reproduces() -> None:
    device = rand_tg_device(PlatformDevice.IOS, unique_id="u")
    assert isinstance(device, DeviceInfo)
    assert device == rand_tg_device(PlatformDevice.IOS, unique_id="u")
    assert rand_tg_device(PlatformDevice.WEB, to_tuple=True, unique_id="u") == tuple(
        rand_tg_device(PlatformDevice.WEB, unique_id="u").to_dict().values()
    )


def test_device_info_model() -> None:
    info = DeviceInfo("Pixel 9", "SDK 35")
    assert str(info) == "Pixel 9 SDK 35"
    assert info.to_dict() == {"device_model": "Pixel 9", "system_version": "SDK 35"}


def test_families_and_rng() -> None:
    assert set(_DEVICES) == set(PlatformDevice)
    assert _rng("a").random() == _rng("a").random()
    assert _rng(5).random() == _rng("5").random()
    assert random_family(_DEVICES.values(), "a") is random_family(_DEVICES.values(), "a")
