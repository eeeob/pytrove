from __future__ import annotations as _annotations

from typing import Any

import pytest

pytest.importorskip("pycountry")
pytest.importorskip("phonenumbers")
pytest.importorskip("babel")

from pytrove.country_tools import _internal  # noqa: E402 - only importable once the skips above have passed.
from pytrove.country_tools._internal import _country_tables, _primary_official_language  # noqa: E402 - only importable once the skips above have passed.


def test_tables_are_built_once() -> None:
    assert _country_tables() is _country_tables()


def test_primary_official_language() -> None:
    assert _primary_official_language("SA") == "ar"
    assert _primary_official_language("AQ") is None


@pytest.mark.parametrize(
    ("rc", "expected"),
    [("CH", "de"), ("BE", "nl"), ("IN", "hi"), ("US", "en"), ("NZ", "en"), ("SN", "wo")],
)
def test_primary_official_language_picks_the_widest_national_language(
    rc: str, expected: str
) -> None:
    assert _primary_official_language(rc) == expected


def test_primary_official_language_ranks_a_regional_language_below_a_national_one() -> None:
    # Ghana: Akan is `official_regional` at 39%, English `official` at 21%.
    assert _primary_official_language("GH") == "en"


def _patch_territory(monkeypatch: pytest.MonkeyPatch, languages: dict[str, Any]) -> None:
    """Make Babel's territory table hold only region `QQ` with `languages`."""
    monkeypatch.setattr(
        _internal,
        "get_global",
        lambda key: {"QQ": languages} if key == "territory_languages" else {},
    )


def test_primary_official_language_falls_back_to_a_regional_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_territory(
        monkeypatch,
        {
            "aa": {"official_status": "official_regional", "population_percent": 5.0},
            "bb": {"official_status": None, "population_percent": 90.0},
        },
    )
    assert _primary_official_language("QQ") == "aa"


def test_primary_official_language_reads_a_missing_population_as_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_territory(
        monkeypatch,
        {
            "aa": {"official_status": "official", "population_percent": None},
            "bb": {"official_status": "official", "population_percent": 1.0},
        },
    )
    assert _primary_official_language("QQ") == "bb"
