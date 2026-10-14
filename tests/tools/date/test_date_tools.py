from datetime import datetime

from pytrove import stamp_to_date, date_to_stamp, date_utc, time_utc, arabic_time
from datetime import timedelta
from pytrove import (
    date_utc_3,
)


def test_stamp_to_date_roundtrip():
    stamp = 1700000000
    date = stamp_to_date(stamp)
    assert isinstance(date, datetime)
    assert date.tzinfo is None  # with_tzinfo defaults to False


def test_stamp_to_date_as_str():
    stamp = 1700000000
    date_str = stamp_to_date(stamp, as_str=True)
    assert isinstance(date_str, str)


def test_stamp_to_date_with_tzinfo():
    date = stamp_to_date(1700000000, with_tzinfo=True)
    assert date.tzinfo is not None


def test_date_to_stamp_default_format():
    stamp = date_to_stamp("24 Jul 2026, 12:00")
    assert isinstance(stamp, int)
    # roundtrip through stamp_to_date should reproduce the same date/time
    back = stamp_to_date(stamp)
    assert (back.year, back.month, back.day, back.hour, back.minute) == (2026, 7, 24, 12, 0)


def test_date_to_stamp_as_float():
    stamp = date_to_stamp("24 Jul 2026, 12:00", as_int=False)
    assert isinstance(stamp, float)


def test_date_utc_returns_naive_datetime_by_default():
    date = date_utc()
    assert isinstance(date, datetime)
    assert date.tzinfo is None


def test_time_utc_int_vs_float():
    assert isinstance(time_utc(), float)
    assert isinstance(time_utc(as_int=True), int)


def test_arabic_time_contains_expected_period_word():
    morning = datetime(2024, 1, 1, 9, 30, 0)
    evening = datetime(2024, 1, 1, 21, 15, 0)
    assert "صباحًا" in arabic_time(morning)
    assert "مساءً" in arabic_time(evening)


def test_arabic_time_midnight_and_noon_hour_conversion():
    midnight = datetime(2024, 1, 1, 0, 0, 0)
    noon = datetime(2024, 1, 1, 12, 0, 0)
    assert "الساعة 12" in arabic_time(midnight)
    assert "الساعة 12" in arabic_time(noon)


def test_date_utc_3_is_labelled_three_hours_ahead():
    value = date_utc_3(with_tzinfo=True)

    assert value.utcoffset() == timedelta(hours=3)
