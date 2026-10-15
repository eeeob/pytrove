from pytrove.country_tools import get_countries_by_cc


def test_get_countries_by_cc_keeps_every_region_sharing_a_calling_code():
    assert len(get_countries_by_cc()[1]) > 1


def test_country_lookups():
    from pytrove import get_cfullname, get_cinfo, get_countries

    assert get_cinfo("SA") == {"cc": 966, "rc": "sa", "flag": "🇸🇦", "name": "Saudi Arabia"}
    assert get_cinfo(966)["rc"] == "sa"
    assert get_cinfo(1)["rc"] == min(c["rc"] for c in get_countries_by_cc()[1])
    assert get_cfullname("sa") == "Saudi Arabia 🇸🇦"
    assert get_countries()["sa"]["cc"] == 966


def test_country_languages():
    from pytrove import get_clanguage_code, get_clanguage_name, get_cname_native

    assert get_clanguage_code("sa") == "ar"
    assert get_cname_native("de") == "Deutschland"
    assert get_clanguage_name("de") == "Deutsch"
    assert get_clanguage_name("de", native=False) == "German"


def test_tables_are_built_once():
    from pytrove.country_tools._internal import _country_tables

    assert _country_tables() is _country_tables()


def test_primary_official_language():
    from pytrove.country_tools._internal import _primary_official_language

    assert _primary_official_language("SA") == "ar"
    assert _primary_official_language("AQ") is None
