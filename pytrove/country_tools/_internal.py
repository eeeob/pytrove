"""Helpers private to `country_tools`: the country tables and the language choice."""

from __future__ import annotations as _annotations

from functools import cache

try:
    from pycountry import countries  # type: ignore[import-not-found]  # Optional: the `country` extra.
except ImportError:
    pass

try:
    from babel.core import get_global  # type: ignore[import-not-found]  # Optional: the `locale` extra.
except ImportError:
    pass

from .._internal import _optional_import
from ..phone_tools import cc_from_rc
from ..typings import CountryInfo, RegionCode
from ..validate_tools import is_rc


@_optional_import("country")
@cache
def _country_tables() -> tuple[dict[str, CountryInfo], dict[int, tuple[CountryInfo, ...]]]:
    """Build the country tables on first use, then reuse them.

    Only regions phonenumbers knows a calling code for are included.

    Returns:
        Countries by lowercase region code, and by calling code with each
        group sorted by region code.
    """
    by_rc: dict[str, CountryInfo] = {
        c.alpha_2.lower(): CountryInfo(
            cc=cc_from_rc(c.alpha_2.lower()), rc=c.alpha_2.lower(), flag=c.flag, name=c.name
        )
        for c in list(countries)
        if is_rc(c.alpha_2)
    }
    grouped: dict[int, list[CountryInfo]] = {}

    for info in by_rc.values():
        grouped.setdefault(info["cc"], []).append(info)

    return by_rc, {
        cc: tuple(sorted(group, key=lambda ci: ci["rc"])) for cc, group in grouped.items()
    }


@_optional_import("locale")
def _primary_official_language(rc: RegionCode) -> str | None:
    """Pick a region's primary official language from Babel's CLDR data.

    Args:
        rc: The uppercase region code.

    Returns:
        The ISO 639 code of the official language with the largest population
        share, or `None` when the data marks none official.
    """
    territory_languages = get_global("territory_languages").get(rc, {})
    official = [lang for lang, info in territory_languages.items() if info.get("official_status")]
    official.sort(
        key=lambda lang: territory_languages[lang]["population_percent"] or 0, reverse=True
    )
    return official[0] if official else None


__all__ = (
    "_country_tables",
    "_primary_official_language",
)
