from pytrove.country_tools import get_countries_by_cc


def test_get_countries_by_cc_keeps_every_region_sharing_a_calling_code():
    assert len(get_countries_by_cc()[1]) > 1
