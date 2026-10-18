from __future__ import annotations as _annotations

import pytest

pytest.importorskip("babel")

from pytrove import get_clanguage_code, get_clanguage_name, get_cname_native  # noqa: E402 - only importable once the skip above has passed.


def test_country_languages() -> None:
    assert get_clanguage_code("sa") == "ar"
    assert get_cname_native("de") == "Deutschland"
    assert get_clanguage_name("de") == "Deutsch"
    assert get_clanguage_name("de", native=False) == "German"
