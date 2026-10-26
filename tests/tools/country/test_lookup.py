from __future__ import annotations as _annotations

from importlib.util import find_spec
from typing import TYPE_CHECKING

import pytest

from pytrove import get_cfullname, get_cinfo, get_countries
from pytrove.country_tools import get_countries_by_cc

if TYPE_CHECKING:
    from collections.abc import Callable

_HAS_COUNTRY = find_spec("pycountry") is not None and find_spec("phonenumbers") is not None

needs_country = pytest.mark.skipif(not _HAS_COUNTRY, reason="needs the `country` extra")


@pytest.mark.skipif(_HAS_COUNTRY, reason="needs the `country` extra to be missing")
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (get_cinfo, ("sa",)),
        (get_cfullname, ("sa",)),
        (get_countries, ()),
        (get_countries_by_cc, ()),
    ],
)
def test_lookup_tools_need_the_country_extra(
    tool: Callable[..., object], args: tuple[object, ...]
) -> None:
    with pytest.raises(ImportError, match=r"pytrove\[country\]"):
        tool(*args)


@needs_country
def test_get_countries_by_cc_keeps_every_region_sharing_a_calling_code() -> None:
    assert len(get_countries_by_cc()[1]) > 1


@needs_country
def test_country_lookups() -> None:
    assert get_cinfo("SA") == {"cc": 966, "rc": "sa", "flag": "🇸🇦", "name": "Saudi Arabia"}
    assert get_cinfo(966)["rc"] == "sa"
    assert get_cinfo(1)["rc"] == min(c["rc"] for c in get_countries_by_cc()[1])
    assert get_cfullname("sa") == "Saudi Arabia 🇸🇦"
    assert get_countries()["sa"]["cc"] == 966


@needs_country
@pytest.mark.parametrize("cc", ["966", "+966", " +966 ", 966])
def test_get_cinfo_reads_a_calling_code_given_as_text_or_int(cc: str | int) -> None:
    assert get_cinfo(cc)["rc"] == "sa"
    assert get_cfullname(cc) == "Saudi Arabia 🇸🇦"


@needs_country
@pytest.mark.parametrize("unknown", ["zz", "999999", 999999])
def test_get_cinfo_and_get_cfullname_raise_key_error_for_an_unknown_code(
    unknown: str | int,
) -> None:
    with pytest.raises(KeyError):
        get_cinfo(unknown)

    with pytest.raises(KeyError):
        get_cfullname(unknown)


@needs_country
def test_country_tables_are_shared_between_calls() -> None:
    assert get_countries() is get_countries()
    assert get_countries_by_cc() is get_countries_by_cc()


@needs_country
def test_every_calling_code_group_is_sorted_by_region_code() -> None:
    groups = get_countries_by_cc()

    assert all(
        [c["rc"] for c in group] == sorted(c["rc"] for c in group) for group in groups.values()
    )
    assert all(c["cc"] == cc for cc, group in groups.items() for c in group)


@needs_country
def test_every_country_has_a_calling_code_and_belongs_to_its_group() -> None:
    by_cc = get_countries_by_cc()

    assert all(info in by_cc[info["cc"]] for info in get_countries().values())
    assert "aq" not in get_countries()  # Antarctica has no calling code
