from __future__ import annotations as _annotations

import pytest

pytest.importorskip("pycountry")
pytest.importorskip("phonenumbers")

from pytrove import get_cfullname, get_cinfo, get_countries  # noqa: E402 - only importable once the skips above have passed.
from pytrove.country_tools import get_countries_by_cc  # noqa: E402


def test_get_countries_by_cc_keeps_every_region_sharing_a_calling_code() -> None:
    assert len(get_countries_by_cc()[1]) > 1


def test_country_lookups() -> None:
    assert get_cinfo("SA") == {"cc": 966, "rc": "sa", "flag": "🇸🇦", "name": "Saudi Arabia"}
    assert get_cinfo(966)["rc"] == "sa"
    assert get_cinfo(1)["rc"] == min(c["rc"] for c in get_countries_by_cc()[1])
    assert get_cfullname("sa") == "Saudi Arabia 🇸🇦"
    assert get_countries()["sa"]["cc"] == 966
