from __future__ import annotations as _annotations

from pytrove.tg_tools._internal import links


def test_short_link_text_threshold() -> None:
    assert links._SHORT_LINK_TEXT == 3


def test_hidden_padding_is_invisible_formatting_and_spaces() -> None:
    assert len(links._HIDDEN_PADDING) > links._SHORT_LINK_TEXT
    assert set(links._HIDDEN_PADDING) <= {"⁪", "⁬", "⁮", " "}
