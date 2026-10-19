from __future__ import annotations as _annotations

from pytrove.text_tools._internal import _smart_split_part, _SNAKE1_PATTERN, _SNAKE2_PATTERN


def test_snake_patterns() -> None:
    assert _SNAKE1_PATTERN.sub(r"\1_\2", "getHTTPResponse") == "getHTTP_Response"
    assert _SNAKE2_PATTERN.sub(r"\1_\2", "getHTTP") == "get_HTTP"


def test_smart_split_part_reports_whether_a_part_is_kept() -> None:
    assert _smart_split_part(" x ", None, True, False, None) == (True, "x")
    assert _smart_split_part(" x ", None, False, False, None) == (True, " x ")
    assert _smart_split_part(" x y ", None, False, True, None) == (True, "xy")
    assert _smart_split_part("5", None, False, False, int) == (True, 5)
    assert _smart_split_part("5", lambda t: False, False, False, int) == (False, None)
    assert _smart_split_part(" 5 ", lambda t: t != "5", True, False, int) == (True, 5)
