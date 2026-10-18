from __future__ import annotations as _annotations

import pytest

pytest.importorskip("pycountry")
pytest.importorskip("phonenumbers")
pytest.importorskip("babel")

from pytrove.country_tools._internal import _country_tables, _primary_official_language  # noqa: E402 - only importable once the skips above have passed.


def test_tables_are_built_once() -> None:
    assert _country_tables() is _country_tables()


def test_primary_official_language() -> None:
    assert _primary_official_language("SA") == "ar"
    assert _primary_official_language("AQ") is None
