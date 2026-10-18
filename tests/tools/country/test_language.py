from __future__ import annotations as _annotations

from importlib.util import find_spec

import pytest

from pytrove import get_clanguage_code, get_clanguage_name, get_cname_native
from pytrove.country_tools import language
from pytrove.errors import ValidationError

_HAS_BABEL = find_spec("babel") is not None

needs_locale = pytest.mark.skipif(not _HAS_BABEL, reason="needs the `locale` extra")


@pytest.mark.skipif(_HAS_BABEL, reason="needs the `locale` extra to be missing")
def test_language_tools_need_the_locale_extra() -> None:
    with pytest.raises(ImportError, match=r"pytrove\[locale\]"):
        get_clanguage_code("sa")


@needs_locale
def test_country_languages() -> None:
    assert get_clanguage_code("sa") == "ar"
    assert get_cname_native("de") == "Deutschland"
    assert get_clanguage_name("de") == "Deutsch"
    assert get_clanguage_name("de", native=False) == "German"


@needs_locale
def test_get_clanguage_code_rejects_a_region_without_an_official_language() -> None:
    with pytest.raises(ValidationError, match="No official language data"):
        get_clanguage_code("aq")


@needs_locale
def test_get_cname_native_falls_back_to_english_for_an_unknown_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(language, "get_clanguage_code", lambda rc: "qqq")
    assert get_cname_native("de") == "Germany"


@needs_locale
def test_get_cname_native_rejects_a_region_without_a_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(language, "get_clanguage_code", lambda rc: "en")

    with pytest.raises(ValidationError, match="No territory name"):
        get_cname_native("qq")


@needs_locale
def test_get_clanguage_name_falls_back_to_english_for_an_unknown_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(language, "get_clanguage_code", lambda rc: "zxx")
    assert get_clanguage_name("de") == "No linguistic content"


@needs_locale
def test_get_clanguage_name_looks_a_script_qualified_code_up_by_its_language(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(language, "get_clanguage_code", lambda rc: "sr_Latn")
    assert get_clanguage_name("rs") == "srpski"
    assert get_clanguage_name("rs", native=False) == "Serbian"


@needs_locale
def test_get_clanguage_name_rejects_a_language_without_a_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(language, "get_clanguage_code", lambda rc: "qqq")

    with pytest.raises(ValidationError, match="No language name"):
        get_clanguage_name("de")
