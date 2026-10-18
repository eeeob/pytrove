from __future__ import annotations as _annotations

from importlib.util import find_spec

import pytest

from pytrove import get_cfullname, get_cinfo, get_countries
from pytrove.country_tools import get_countries_by_cc

_HAS_COUNTRY = find_spec("pycountry") is not None and find_spec("phonenumbers") is not None

needs_country = pytest.mark.skipif(not _HAS_COUNTRY, reason="needs the `country` extra")


@pytest.mark.skipif(_HAS_COUNTRY, reason="needs the `country` extra to be missing")
def test_lookup_tools_need_the_country_extra() -> None:
    with pytest.raises(ImportError, match=r"pytrove\[country\]"):
        get_cinfo("sa")


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
