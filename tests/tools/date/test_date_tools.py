from __future__ import annotations as _annotations

import locale
import sys
import time
from datetime import datetime, timedelta, timezone, tzinfo
from datetime import time as time_of_day
from typing import TYPE_CHECKING

import pytest

from pytrove import date_tools
from pytrove.constants import TZ_UTC_PLUS_3
from pytrove.date_tools import (
    arabic_time,
    date_to_stamp,
    date_utc,
    date_utc_3,
    stamp_to_date,
    time_utc,
    time_utc_3,
)

if sys.version_info >= (3, 11):
    from typing import assert_type
else:
    from typing_extensions import assert_type

if TYPE_CHECKING:
    from collections.abc import Iterator

_STAMP = 1700000000
_STAMP_DATE = datetime(2023, 11, 14, 22, 13, 20)
_NOT_ENGLISH_LOCALES = ("fr_FR.UTF-8", "fr_FR", "French_France.1252", "de_DE.UTF-8", "de_DE")


class _UtcMinus5(tzinfo):
    """A `tzinfo` that is not a `timezone`, as `zoneinfo.ZoneInfo` is."""

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=-5)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "UTC-5"


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin `time.time()` to half a second past the epoch."""
    monkeypatch.setattr(time, "time", lambda: 0.5)


@pytest.fixture
def restore_lc_time() -> Iterator[None]:
    """Put the `LC_TIME` locale back after a test changes it."""
    saved = locale.setlocale(locale.LC_TIME)
    yield
    locale.setlocale(locale.LC_TIME, saved)


def test_all_lists_exactly_the_date_tools() -> None:
    assert date_tools.__all__ == (
        "stamp_to_date",
        "date_to_stamp",
        "date_utc_3",
        "date_utc",
        "time_utc_3",
        "time_utc",
        "arabic_time",
    )


def test_overloads_pick_the_return_type_from_the_flag(frozen_clock: None) -> None:
    assert_type(stamp_to_date(0), datetime)
    assert_type(stamp_to_date(0, as_str=True), str)
    assert_type(stamp_to_date(0, None, True), str)
    assert_type(date_to_stamp("1 Jan 2020, 00:00"), int)
    assert_type(date_to_stamp("1 Jan 2020, 00:00", as_int=False), float)
    assert_type(date_to_stamp("1 Jan 2020, 00:00", None, "%d %b %Y, %H:%M", False), float)
    assert_type(date_utc(), datetime)
    assert_type(date_utc(as_str=True), str)
    assert_type(date_utc_3(), datetime)
    assert_type(date_utc_3(True), str)
    assert_type(time_utc(), float)
    assert_type(time_utc(True), int)
    assert_type(time_utc_3(), float)
    assert_type(time_utc_3(True), int)


def test_stamp_to_date_roundtrips_through_date_to_stamp() -> None:
    date = stamp_to_date(_STAMP)

    assert date == _STAMP_DATE
    assert date.tzinfo is None  # `keep_tzinfo` defaults to `False`
    assert date_to_stamp(str(date), format="%Y-%m-%d %H:%M:%S") == _STAMP


@pytest.mark.parametrize(
    ("stamp", "keep_tzinfo", "expected"),
    [
        (_STAMP, False, "2023-11-14 22:13:20"),
        (_STAMP + 0.5, False, "2023-11-14 22:13:20"),
        (_STAMP + 0.5, True, "2023-11-14 22:13:20.500000+00:00"),
    ],
)
def test_stamp_to_date_as_str(stamp: float, keep_tzinfo: bool, expected: str) -> None:
    assert stamp_to_date(stamp, as_str=True, keep_tzinfo=keep_tzinfo) == expected


def test_stamp_to_date_keep_tzinfo_keeps_zone_and_microseconds() -> None:
    date = stamp_to_date(0.5, keep_tzinfo=True)

    assert date == datetime(1970, 1, 1, 0, 0, 0, 500000, tzinfo=timezone.utc)
    assert date.tzinfo is timezone.utc


def test_stamp_to_date_drops_zone_and_microseconds_by_default() -> None:
    assert stamp_to_date(0.5) == datetime(1970, 1, 1)
    assert stamp_to_date(0.5).microsecond == 0


def test_stamp_to_date_in_another_zone() -> None:
    assert stamp_to_date(0, TZ_UTC_PLUS_3) == datetime(1970, 1, 1, 3, 0)


def test_stamp_to_date_accepts_any_tzinfo() -> None:
    date = stamp_to_date(0, _UtcMinus5(), keep_tzinfo=True)

    assert date.utcoffset() == timedelta(hours=-5)
    assert date.replace(tzinfo=None) == datetime(1969, 12, 31, 19, 0)


def test_stamp_to_date_with_no_zone_gives_naive_local_time() -> None:
    stamp = _STAMP + 0.5

    assert stamp_to_date(stamp, None) == datetime.fromtimestamp(stamp).replace(microsecond=0)
    kept = stamp_to_date(stamp, None, keep_tzinfo=True)
    assert kept.tzinfo is None
    assert kept == datetime.fromtimestamp(stamp)


def test_stamp_to_date_floors_a_negative_stamp() -> None:
    assert stamp_to_date(-0.5) == datetime(1969, 12, 31, 23, 59, 59)


@pytest.mark.parametrize(
    ("stamp", "error"),
    [(float("nan"), ValueError), (float("inf"), OverflowError), (1e20, OverflowError)],
)
def test_stamp_to_date_rejects_an_invalid_stamp(stamp: float, error: type[Exception]) -> None:
    with pytest.raises(error):
        stamp_to_date(stamp)


@pytest.mark.skipif(
    sys.platform != "win32", reason="the Windows C runtime rejects pre-epoch local time"
)
def test_local_zone_rejects_pre_epoch_values_on_windows() -> None:
    with pytest.raises(OSError):  # noqa: PT011 - `OSError` carries no message worth matching.
        stamp_to_date(-1, None)
    with pytest.raises(OSError):  # noqa: PT011 - `OSError` carries no message worth matching.
        date_to_stamp("1 Jan 1960, 00:00", tz=None)


def test_date_to_stamp_default_format() -> None:
    stamp = date_to_stamp("24 Jul 2026, 12:00")
    assert stamp == 1784894400
    assert stamp_to_date(stamp) == datetime(2026, 7, 24, 12, 0)


def test_date_to_stamp_reads_a_naive_date_in_the_given_zone() -> None:
    assert date_to_stamp("1 Jan 1970, 03:00", TZ_UTC_PLUS_3) == 0
    assert date_to_stamp("1 Jan 1970, 00:00", _UtcMinus5()) == 5 * 3600


def test_date_to_stamp_with_no_zone_reads_local_time() -> None:
    assert date_to_stamp("1 Jan 2020, 00:00", None) == int(datetime(2020, 1, 1).timestamp())


def test_date_to_stamp_reads_a_zone_aware_format_as_is() -> None:
    assert date_to_stamp("1970-01-01 03:00 +0300", format="%Y-%m-%d %H:%M %z") == 0
    assert date_to_stamp("1970-01-01 00:00 +0000", TZ_UTC_PLUS_3, "%Y-%m-%d %H:%M %z") == 0


@pytest.mark.parametrize(
    ("date", "as_int", "expected"),
    [
        ("2020-01-01 00:00:00.5", False, 1577836800.5),
        ("2020-01-01 00:00:00.5", True, 1577836800),
        ("1969-12-31 23:59:59.5", False, -0.5),
        ("1969-12-31 23:59:59.5", True, -1),
        ("1960-01-01 00:00:00.5", True, -315619200),
    ],
)
def test_date_to_stamp_floors_fractional_seconds(date: str, as_int: bool, expected: float) -> None:
    stamp = date_to_stamp(date, format="%Y-%m-%d %H:%M:%S.%f", as_int=as_int)

    assert stamp == expected
    assert isinstance(stamp, int if as_int else float)


def test_date_to_stamp_floor_matches_stamp_to_date() -> None:
    stamp = date_to_stamp("1969-12-31 23:59:59.5", format="%Y-%m-%d %H:%M:%S.%f")

    assert stamp_to_date(stamp) == datetime(1969, 12, 31, 23, 59, 59)


def test_date_to_stamp_before_the_epoch() -> None:
    assert date_to_stamp("1 Jan 1960, 00:00") == -315619200


@pytest.mark.parametrize("date", ["not a date", "1 Jan 2020"])
def test_date_to_stamp_rejects_a_mismatched_format(date: str) -> None:
    with pytest.raises(ValueError, match="does not match format"):
        date_to_stamp(date)


@pytest.mark.usefixtures("restore_lc_time")
def test_date_to_stamp_default_format_reads_english_under_the_c_locale() -> None:
    locale.setlocale(locale.LC_TIME, "C")

    assert date_to_stamp("1 Jan 2020, 00:00") == 1577836800


@pytest.mark.usefixtures("restore_lc_time")
def test_date_to_stamp_default_format_follows_lc_time() -> None:
    for name in _NOT_ENGLISH_LOCALES:
        try:
            locale.setlocale(locale.LC_TIME, name)
            break
        except locale.Error:
            continue
    else:
        pytest.skip("no non-English locale is installed")

    with pytest.raises(ValueError, match="does not match format"):
        date_to_stamp("1 May 2020, 00:00")


@pytest.mark.usefixtures("frozen_clock")
def test_date_utc_reads_the_clock_in_utc() -> None:
    assert date_utc() == datetime(1970, 1, 1)
    assert date_utc().tzinfo is None
    assert date_utc(as_str=True) == "1970-01-01 00:00:00"
    aware = date_utc(keep_tzinfo=True)
    assert aware == datetime(1970, 1, 1, 0, 0, 0, 500000, tzinfo=timezone.utc)
    assert aware.tzinfo is timezone.utc


@pytest.mark.usefixtures("frozen_clock")
def test_date_utc_3_reads_the_clock_three_hours_ahead() -> None:
    assert date_utc_3() == datetime(1970, 1, 1, 3, 0)
    assert date_utc_3().tzinfo is None
    assert date_utc_3(as_str=True) == "1970-01-01 03:00:00"
    aware = date_utc_3(keep_tzinfo=True)
    assert aware.utcoffset() == timedelta(hours=3)
    assert aware.replace(tzinfo=None) == datetime(1970, 1, 1, 3, 0, 0, 500000)


@pytest.mark.usefixtures("frozen_clock")
def test_time_utc_returns_the_clock() -> None:
    assert time_utc() == 0.5
    assert isinstance(time_utc(), float)
    assert time_utc(as_int=True) == 0
    assert isinstance(time_utc(as_int=True), int)


@pytest.mark.usefixtures("frozen_clock")
def test_time_utc_3_adds_three_hours() -> None:
    assert time_utc_3() == 10800.5
    assert isinstance(time_utc_3(), float)
    assert time_utc_3(True) == 10800
    assert isinstance(time_utc_3(True), int)


def test_arabic_time_contains_expected_period_word() -> None:
    morning = datetime(2024, 1, 1, 9, 30, 0)
    evening = datetime(2024, 1, 1, 21, 15, 0)
    assert "صباحًا" in arabic_time(morning)
    assert "مساءً" in arabic_time(evening)


def test_arabic_time_midnight_and_noon_hour_conversion() -> None:
    midnight = datetime(2024, 1, 1, 0, 0, 0)
    noon = datetime(2024, 1, 1, 12, 0, 0)
    assert "الساعة 12" in arabic_time(midnight)
    assert "الساعة 12" in arabic_time(noon)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2024, 1, 1, 9, 0, 0), "الساعة 9 صباحًا"),
        (datetime(2024, 1, 1, 11, 59, 59), "الساعة 11 و 59 دقيقة و 59 ثانية صباحًا"),
        (datetime(2024, 1, 1, 15, 5, 0), "الساعة 3 و 5 دقيقة مساءً"),
        (datetime(2024, 1, 1, 23, 0, 0), "الساعة 11 مساءً"),
        (datetime(2024, 1, 1, 0, 0, 7), "الساعة 12 و 7 ثانية صباحًا"),
        (datetime(2024, 1, 1, 12, 30, 15), "الساعة 12 و 30 دقيقة و 15 ثانية مساءً"),
        (datetime(2024, 1, 1, 0, 0, 0, 500000), "الساعة 12 صباحًا"),
        (datetime(2024, 1, 1, 15, 5, tzinfo=TZ_UTC_PLUS_3), "الساعة 3 و 5 دقيقة مساءً"),
        (time_of_day(15, 5), "الساعة 3 و 5 دقيقة مساءً"),
    ],
)
def test_arabic_time_mentions_only_non_zero_parts(
    moment: datetime | time_of_day, expected: str
) -> None:
    assert arabic_time(moment) == expected


@pytest.mark.usefixtures("frozen_clock")
def test_arabic_time_defaults_to_now_in_utc_plus_3() -> None:
    assert arabic_time() == "الساعة 3 صباحًا"
