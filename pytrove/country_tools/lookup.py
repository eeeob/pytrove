"""Looking countries up by region code or calling code."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

from .._internal import _optional_import
from ._internal import _country_tables

if TYPE_CHECKING:
    from ..typings import CountryInfo, StrInt


@_optional_import("country")
def get_cinfo(rc_or_cc: StrInt) -> CountryInfo:
    """Look one country up by region code or calling code.

    A calling code shared by several regions (+1) gives the first by region
    code; `get_countries_by_cc` lists them all.

    Args:
        rc_or_cc: A region code in any case, or a calling code.

    Returns:
        The country.

    Raises:
        KeyError: If nothing matches.
    """
    by_rc, by_cc = _country_tables()

    if isinstance(rc_or_cc, str):
        return by_rc[rc_or_cc.lower()]

    return by_cc[rc_or_cc][0]


@_optional_import("country")
def get_cfullname(rc_or_cc: StrInt) -> str:
    """Return a country's English name followed by its flag.

    Args:
        rc_or_cc: A region code or a calling code.

    Returns:
        Such as `"Saudi Arabia 🇸🇦"`.

    Raises:
        KeyError: If nothing matches.
    """
    info = get_cinfo(rc_or_cc)
    return f"{info['name']} {info['flag']}"


@_optional_import("country")
def get_countries() -> dict[str, CountryInfo]:
    """Return every country by lowercase region code.

    Returns:
        The shared table; do not mutate it.
    """
    return _country_tables()[0]


@_optional_import("country")
def get_countries_by_cc() -> dict[int, tuple[CountryInfo, ...]]:
    """Return every country grouped by calling code, each group sorted by region code.

    Returns:
        The shared table; do not mutate it.
    """
    return _country_tables()[1]


__all__ = (
    "get_cinfo",
    "get_cfullname",
    "get_countries",
    "get_countries_by_cc",
)
