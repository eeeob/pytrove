from __future__ import annotations as _annotations

from pytrove.tg_tools._internal import links


def test_short_link_text_threshold() -> None:
    assert links._SHORT_LINK_TEXT == 3
