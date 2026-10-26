from __future__ import annotations as _annotations

import pytest

from pytrove._internal._phone import _normalize_phone_text


@pytest.mark.parametrize(
    ("text", "clean", "resolve", "expected"),
    [
        ("00966 50-123\t4567", True, True, "+966501234567"),
        ("966501234567", True, True, "+966501234567"),
        ("+966501234567", True, True, "+966501234567"),
        ("+00966", True, True, "+00966"),
        ("966 50-1", False, True, "+966 50-1"),
        ("00966 50-1", True, False, "00966501"),
        ("966 50", False, False, "966 50"),
    ],
)
def test_normalize_phone_text(text: str, clean: bool, resolve: bool, expected: str) -> None:
    assert _normalize_phone_text(text, clean, resolve) == expected


def test_normalize_phone_text_cleans_and_resolves_by_default() -> None:
    assert _normalize_phone_text("00 966-5") == "+9665"
