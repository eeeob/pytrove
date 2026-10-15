from __future__ import annotations as _annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from pytrove.date_tools import (
    arabic_time,
    date_to_stamp,
    date_utc,
    date_utc_3,
    stamp_to_date,
    time_utc,
    time_utc_3,
    UTC_PLUS_3,
)


def test_utc_plus_3_is_a_fixed_three_hour_offset() -> None:
    assert UTC_PLUS_3.utcoffset(None) == timedelta(hours=3)


def test_stamp_to_date_in_another_zone() -> None:
    assert stamp_to_date(0, UTC_PLUS_3) == datetime(1970, 1, 1, 3, 0)


def test_date_to_stamp_reads_a_zone_aware_format_as_is() -> None:
    assert date_to_stamp("1970-01-01 03:00 +0300", format="%Y-%m-%d %H:%M %z") == 0


def test_date_to_stamp_rejects_a_mismatched_format() -> None:
    with pytest.raises(ValueError):
        date_to_stamp("not a date")


def test_date_utc_3_variants() -> None:
    aware = date_utc_3(with_tzinfo=True)
    assert aware.utcoffset() == timedelta(hours=3)
    assert isinstance(date_utc_3(as_str=True), str)
    assert date_utc_3().tzinfo is None
    assert date_utc_3().microsecond == 0


def test_date_utc_keeps_the_zone_when_asked() -> None:
    assert date_utc(with_tzinfo=True).tzinfo is timezone.utc
    assert isinstance(date_utc(as_str=True), str)


def test_time_utc_3_is_three_hours_ahead_of_time_utc() -> None:
    assert abs(time_utc_3() - time_utc() - 3 * 3600) < 5
    assert isinstance(time_utc_3(True), int)
    assert abs(time_utc() - time.time()) < 5


@pytest.mark.parametrize(("moment", "expected"), [
    (datetime(2024, 1, 1, 9, 0, 0), "الساعة 9 صباحًا"),
    (datetime(2024, 1, 1, 15, 5, 0), "الساعة 3 و 5 دقيقة مساءً"),
    (datetime(2024, 1, 1, 0, 0, 7), "الساعة 12 و 7 ثانية صباحًا"),
    (datetime(2024, 1, 1, 12, 30, 15), "الساعة 12 و 30 دقيقة و 15 ثانية مساءً"),
])
def test_arabic_time_mentions_only_non_zero_parts(moment: datetime, expected: str) -> None:
    assert arabic_time(moment) == expected


def test_arabic_time_defaults_to_now_in_utc_plus_3() -> None:
    assert arabic_time().startswith("الساعة ")
