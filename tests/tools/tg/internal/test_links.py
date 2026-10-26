from __future__ import annotations as _annotations

import pytest

from pytrove.tg_tools._internal import links


def test_short_link_text_threshold() -> None:
    assert links._SHORT_LINK_TEXT == 3


def test_hidden_padding_is_invisible_formatting_and_spaces() -> None:
    assert len(links._HIDDEN_PADDING) > links._SHORT_LINK_TEXT
    assert set(links._HIDDEN_PADDING) <= {"⁪", "⁬", "⁮", " "}


def test_private_chat_link_pattern_captures_the_path_after_c() -> None:
    assert links._PRIVATE_CHAT_LINK_PATTERN.match("https://T.me/c/123/4").group(1) == "123/4"
    assert links._PRIVATE_CHAT_LINK_PATTERN.match("https://t.me/name/4") is None
    assert links._PRIVATE_CHAT_LINK_PATTERN.match("https://t.me/c/name") is None


def test_preview_link_pattern_captures_the_channel_name() -> None:
    assert links._PREVIEW_LINK_PATTERN.match("https://t.me/s/name/12").group(1) == "name"
    assert links._PREVIEW_LINK_PATTERN.match("T.ME/S/Name").group(1) == "Name"
    assert links._PREVIEW_LINK_PATTERN.match("https://t.me/name") is None


@pytest.mark.parametrize("host", ["t.me", "telegram.me", "telegram.dog", "telegram.org"])
def test_link_patterns_accept_every_telegram_host(host: str) -> None:
    assert links._PRIVATE_CHAT_LINK_PATTERN.match(f"{host}/c/123/4").group(1) == "123/4"
    assert links._PREVIEW_LINK_PATTERN.match(f"{host}/s/name").group(1) == "name"


@pytest.mark.parametrize("host", ["t.org", "t.dog", "telegram.com"])
def test_link_patterns_refuse_other_hosts(host: str) -> None:
    assert links._PRIVATE_CHAT_LINK_PATTERN.match(f"{host}/c/123") is None
    assert links._PREVIEW_LINK_PATTERN.match(f"{host}/s/name") is None


def test_link_patterns_refuse_a_trailing_newline() -> None:
    assert links._PRIVATE_CHAT_LINK_PATTERN.match("t.me/c/123\n") is None
    assert links._PREVIEW_LINK_PATTERN.match("t.me/s/name\n") is None


def test_private_chat_link_pattern_needs_a_numeric_id() -> None:
    assert links._PRIVATE_CHAT_LINK_PATTERN.match("t.me/c/123abc") is None
    assert links._PRIVATE_CHAT_LINK_PATTERN.match("t.me/c/123/").group(1) == "123/"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://t.me/+AbCd", ("invite", "https://t.me/+AbCd")),
        ("HTTPS://T.ME/+AbCd", ("invite", "HTTPS://T.ME/+AbCd")),
        ("T.ME/JOINCHAT/AbCd", ("invite", "T.ME/JOINCHAT/AbCd")),
        ("https://t.me/c/123/4", ("private", "123/4")),
        ("T.ME/C/123", ("private", "123")),
        ("https://t.me/s/Name", ("link", "name")),
        ("HTTPS://T.ME/Name/5", ("link", "name")),
        ("telegram.dog/x", ("link", "x")),
        ("@Name", ("text", "@Name")),
        ("-100123", ("text", "-100123")),
        ("https://example.com/x", ("text", "https://example.com/x")),
    ],
)
def test_classify_tg_target(text: str, expected: tuple[str, str]) -> None:
    assert links._classify_tg_target(text) == expected
