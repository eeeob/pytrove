from typing import Dict, Union, Optional

from .typings import CountryInfo, RegionCode, StrInt
from .phone_tools import cc_from_rc, is_rc
from .validate_tools import validation

try:
    from pycountry import countries
except ImportError:
    pass

try:
    from babel import Locale, UnknownLocaleError
    from babel.core import get_global
except ImportError:
    pass

from ._optional import _optional_import

_COUNTRIES: Optional[Dict[str, CountryInfo]] = None
_COUNTRIES_BY_CC: Optional[Dict[int, CountryInfo]] = None

@_optional_import((("pycountry", "phonenumbers"), "country"))
def _build_countries():
    global _COUNTRIES, _COUNTRIES_BY_CC

    if _COUNTRIES is not None:
        return

    _COUNTRIES = {
        c._fields["alpha_2"].lower(): dict(
            cc=cc_from_rc(c._fields["alpha_2"].lower()),
            rc=c._fields["alpha_2"].lower(),
            flag=c._fields["flag"],
            name=c._fields["name"]
        )
        for c in list(countries)
        if is_rc(c._fields["alpha_2"])
    }

    _COUNTRIES_BY_CC = {
        ci["cc"]: ci
        for ci in _COUNTRIES.values()
    }


@_optional_import((("pycountry", "phonenumbers"), "country"))
def get_cinfo(rc_or_cc: StrInt) -> CountryInfo:
    _build_countries()
    if isinstance(rc_or_cc, str):
        return _COUNTRIES[rc_or_cc.lower()]
    return _COUNTRIES_BY_CC[rc_or_cc]


@_optional_import((("pycountry", "phonenumbers"), "country"))
def get_cfullname(rc_or_cc: StrInt) -> str:
    info = get_cinfo(rc_or_cc)
    return f"{info['name']} {info['flag']}"


@_optional_import(("babel", "locale"))
def _primary_official_language(rc: RegionCode) -> Optional[str]:
    """ISO 639 code of `rc`'s primary official language, picked from Babel's
    CLDR territory-language data by highest population share among languages
    marked official there; `None` if the territory has no language marked
    official in that data.
    """

    territory_languages = get_global("territory_languages").get(rc, {})
    official_languages = [
        lang for lang, info in territory_languages.items()
        if info.get("official_status")
    ]
    official_languages.sort(
        key=lambda lang: territory_languages[lang]["population_percent"] or 0,
        reverse=True,
    )

    return official_languages[0] if official_languages else None


@_optional_import(("babel", "locale"))
def get_clanguage_code(rc: RegionCode) -> str:
    """Return the ISO 639 code of the country's primary official language,
    e.g. `"ar"` for `sa` (Saudi Arabia), the full language name/autonym
    `get_clanguage_name` is built from.
    """

    rc = rc.upper()
    language = _primary_official_language(rc)

    validation(language is not None, f"No official language data for region code - {rc}")

    return language


@_optional_import(("babel", "locale"))
def get_cname_native(rc: RegionCode) -> str:
    """Return the country's name written in its own primary official
    language, e.g. "Deutschland" for `de`/49 instead of the English
    "Germany" that `get_cinfo`/`get_cfullname` give.

    `Locale(language, territory=rc)` is deliberately avoided: Babel only
    ships that combined identifier for a handful of territories (`en_US`,
    `de_DE`, ...), so e.g. `Locale("ar", territory="SA")` raises
    `UnknownLocaleError` even though Arabic data for Saudi Arabia exists --
    it just isn't filed under that exact locale id. Looking the territory
    code up in the plain language locale's `.territories` table is what
    actually has that data.
    """

    rc = rc.upper()
    language = get_clanguage_code(rc)

    try:
        locale = Locale.parse(language)
    except UnknownLocaleError:
        locale = Locale("en")

    name = locale.territories.get(rc) or Locale("en").territories.get(rc)

    validation(name is not None, f"No territory name available for region code - {rc}")

    return name


@_optional_import(("babel", "locale"))
def get_clanguage_name(rc: RegionCode, native: bool = True) -> str:
    """Return the display name of the country's primary official language,
    e.g. "German" for `de`/49, or its own autonym ("Deutsch") when
    `native=True`.

    Looked up the same way as `get_cname_native`: `language` is used as a
    dict key into a display locale's `.languages` table rather than parsed
    as its own locale, since a handful of official languages (e.g. Samoan,
    Bislama) have no Babel locale data of their own to report an autonym
    from, but are still present as entries in other locales' tables.
    """

    rc = rc.upper()
    language = get_clanguage_code(rc)

    # `.languages` tables are keyed by the bare language subtag -- a
    # script-qualified code like "sr_Latn" (Montenegro) parses fine as its
    # own locale, but must be looked up in that table as just "sr".
    base_language = language.split("_")[0]

    try:
        locale = Locale.parse(language) if native else Locale("en")
    except UnknownLocaleError:
        locale = Locale("en")

    name = locale.languages.get(base_language) or Locale("en").languages.get(base_language)

    validation(name is not None, f"No language name available for language code - {language}")

    return name


@_optional_import((("pycountry", "phonenumbers"), "country"))
def get_countries() -> Dict[str, CountryInfo]:
    _build_countries()
    return _COUNTRIES

@_optional_import((("pycountry", "phonenumbers"), "country"))
def get_countries_by_cc() -> Dict[int, CountryInfo]:
    _build_countries()
    return _COUNTRIES_BY_CC


__all__ = (
    "get_cinfo",
    "get_cfullname",
    "get_cname_native",
    "get_clanguage_code",
    "get_clanguage_name",
    "get_countries",
    "get_countries_by_cc",
)