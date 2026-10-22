"""A country's official language and its name in that language."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

try:
    from babel import Locale, UnknownLocaleError
except ImportError:
    pass

from .._internal._optional import _optional_import
from ..errors import ValidationError
from ._internal import _primary_official_language

if TYPE_CHECKING:
    from ..typings import RegionCode


@_optional_import(("babel", "locale"))
def get_clanguage_code(rc: RegionCode) -> str:
    """Return the ISO 639 code of a country's primary official language: `"sa"` gives `"ar"`.

    Args:
        rc: The region code, in any case.

    Returns:
        The language code.

    Raises:
        ValidationError: If no official language is recorded.
    """
    rc = rc.upper()
    language = _primary_official_language(rc)

    if language is None:
        msg = f"No official language data for region code - {rc}"
        raise ValidationError(msg)

    return language


@_optional_import(("babel", "locale"))
def get_cname_native(rc: RegionCode) -> str:
    """Return a country's name in its own official language: `"de"` gives `"Deutschland"`.

    The name comes from the language locale's territory table, since Babel
    lacks most combined locales such as `ar_SA`; English is the fallback.

    Args:
        rc: The region code, in any case.

    Returns:
        The native name.

    Raises:
        ValidationError: If no language or no name is available.
    """
    rc = rc.upper()
    language = get_clanguage_code(rc)

    try:
        locale = Locale.parse(language)
    except UnknownLocaleError:
        locale = Locale("en")

    name = locale.territories.get(rc) or Locale("en").territories.get(rc)

    if name is None:
        msg = f"No territory name available for region code - {rc}"
        raise ValidationError(msg)

    return name


@_optional_import(("babel", "locale"))
def get_clanguage_name(rc: RegionCode, native: bool = True) -> str:
    """Return the name of a country's official language, natively (`"Deutsch"`) or in English.

    A script-qualified code such as `sr_Latn` is looked up by its bare
    language; a language without locale data falls back to English.

    Args:
        rc: The region code, in any case.
        native: Whether to name the language in itself.

    Returns:
        The language's name.

    Raises:
        ValidationError: If no language or no name is available.
    """
    rc = rc.upper()
    language = get_clanguage_code(rc)
    base_language = language.split("_")[0]

    try:
        locale = Locale.parse(language) if native else Locale("en")
    except UnknownLocaleError:
        locale = Locale("en")

    name = locale.languages.get(base_language) or Locale("en").languages.get(base_language)

    if name is None:
        msg = f"No language name available for language code - {language}"
        raise ValidationError(msg)

    return name


__all__ = (
    "get_clanguage_code",
    "get_cname_native",
    "get_clanguage_name",
)
