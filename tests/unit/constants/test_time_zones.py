"""`pytrove.constants.time_zones`: the fixed offsets and the names they print."""

from __future__ import annotations as _annotations

from datetime import datetime, timedelta

from pytrove.constants import time_zones
from pytrove.constants.time_zones import TZ_UTC_PLUS_3


def test_tz_utc_plus_3_is_a_fixed_three_hour_offset_named_utc_plus_3() -> None:
    assert TZ_UTC_PLUS_3.utcoffset(None) == timedelta(hours=3)
    assert TZ_UTC_PLUS_3.tzname(None) == "UTC+3"
    assert datetime(2020, 1, 1, tzinfo=TZ_UTC_PLUS_3).strftime("%Z %z") == "UTC+3 +0300"


def test_all_lists_exactly_the_time_zones() -> None:
    assert time_zones.__all__ == ("TZ_UTC_PLUS_3",)
