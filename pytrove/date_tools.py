"""Timestamps, dates in UTC and UTC+3, and Arabic time display."""

from __future__ import annotations as _annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, overload

from .constants import TZ_UTC_PLUS_3
from .enums import TimeUnit

if TYPE_CHECKING:
    from .typings import Number, _False, _True


@overload
def stamp_to_date(
    stamp_time: Number,
    tz: timezone | None = timezone.utc,
    as_str: _False = False,
    with_tzinfo: bool = False,
) -> datetime: ...
@overload
def stamp_to_date(
    stamp_time: Number, tz: timezone | None, as_str: _True, with_tzinfo: bool = False
) -> str: ...
@overload
def stamp_to_date(
    stamp_time: Number,
    tz: timezone | None = timezone.utc,
    *,
    as_str: _True,
    with_tzinfo: bool = False,
) -> str: ...
def stamp_to_date(
    stamp_time: Number,
    tz: timezone | None = timezone.utc,
    as_str: bool = False,
    with_tzinfo: bool = False,
) -> datetime | str:
    """Turn a Unix timestamp into a date in a time zone.

    Args:
        stamp_time: Seconds since the epoch.
        tz: The zone to express it in; `None` for the machine's local zone.
        as_str: Whether to return `str(date)` instead of the `datetime`.
        with_tzinfo: Whether to keep the zone and microseconds; otherwise both are dropped.

    Returns:
        The date, or its string form.

    Example:
        >>> stamp_to_date(0)
        datetime.datetime(1970, 1, 1, 0, 0)
        >>> stamp_to_date(0, as_str=True)
        '1970-01-01 00:00:00'
        >>> stamp_to_date(0.5, with_tzinfo=True)
        datetime.datetime(1970, 1, 1, 0, 0, 0, 500000, tzinfo=datetime.timezone.utc)
    """
    date = datetime.fromtimestamp(stamp_time, tz)

    if not with_tzinfo:
        date = date.replace(tzinfo=None, microsecond=0)

    return str(date) if as_str else date


@overload
def date_to_stamp(
    date: str,
    tz: timezone | None = timezone.utc,
    format: str = "%d %b %Y, %H:%M",
    as_int: _True = True,
) -> int: ...
@overload
def date_to_stamp(date: str, tz: timezone | None, format: str, as_int: _False) -> float: ...
@overload
def date_to_stamp(
    date: str,
    tz: timezone | None = timezone.utc,
    format: str = "%d %b %Y, %H:%M",
    *,
    as_int: _False,
) -> float: ...
def date_to_stamp(
    date: str,
    tz: timezone | None = timezone.utc,
    format: str = "%d %b %Y, %H:%M",
    as_int: bool = True,
) -> int | float:
    """Turn a date string into a Unix timestamp.

    Args:
        date: The date text.
        tz: The zone a date without one is read in; `None` for local time.
        format: The `strptime` format of `date`.
        as_int: Whether to drop the fractional seconds.

    Returns:
        Seconds since the epoch.

    Raises:
        ValueError: If `date` does not match `format`.

    Example:
        >>> date_to_stamp("1 Jan 2020, 00:00")
        1577836800
        >>> date_to_stamp("2020-01-01", format="%Y-%m-%d", as_int=False)
        1577836800.0
    """
    dt = datetime.strptime(date, format)

    if dt.tzinfo is None and tz is not None:
        dt = dt.replace(tzinfo=tz)

    return int(dt.timestamp()) if as_int else dt.timestamp()


@overload
def date_utc_3(as_str: _False = False, with_tzinfo: bool = False) -> datetime: ...
@overload
def date_utc_3(as_str: _True, with_tzinfo: bool = False) -> str: ...
def date_utc_3(as_str: bool = False, with_tzinfo: bool = False) -> datetime | str:
    """Return the current date and time in UTC+3.

    Args:
        as_str: Whether to return `str(date)` instead of the `datetime`.
        with_tzinfo: Whether to keep the zone and microseconds.

    Returns:
        The current date in UTC+3, or its string form.
    """
    return stamp_to_date(time.time(), TZ_UTC_PLUS_3, as_str, with_tzinfo)


@overload
def date_utc(as_str: _False = False, with_tzinfo: bool = False) -> datetime: ...
@overload
def date_utc(as_str: _True, with_tzinfo: bool = False) -> str: ...
def date_utc(as_str: bool = False, with_tzinfo: bool = False) -> datetime | str:
    """Return the current date and time in UTC.

    Args:
        as_str: Whether to return `str(date)` instead of the `datetime`.
        with_tzinfo: Whether to keep the zone and microseconds.

    Returns:
        The current date in UTC, or its string form.
    """
    return stamp_to_date(time.time(), timezone.utc, as_str, with_tzinfo)


@overload
def time_utc_3(as_int: _False = False) -> float: ...
@overload
def time_utc_3(as_int: _True) -> int: ...
def time_utc_3(as_int: bool = False) -> int | float:
    """Return the Unix timestamp shifted forward by three hours.

    A timestamp has no zone, so this is not the time in UTC+3: it is
    `time_utc()` plus three hours, kept for backward compatibility.

    Args:
        as_int: Whether to drop the fractional seconds.

    Returns:
        The shifted timestamp.
    """
    stamp_time = time.time() + TimeUnit.HOUR * 3
    return int(stamp_time) if as_int else stamp_time


@overload
def time_utc(as_int: _False = False) -> float: ...
@overload
def time_utc(as_int: _True) -> int: ...
def time_utc(as_int: bool = False) -> int | float:
    """Return the current Unix timestamp.

    Args:
        as_int: Whether to drop the fractional seconds.

    Returns:
        Seconds since the epoch.
    """
    stamp_time = time.time()
    return int(stamp_time) if as_int else stamp_time


def arabic_time(date: datetime | None = None) -> str:
    """Say a time of day in Arabic, on a 12-hour clock.

    Minutes and seconds are mentioned only when not zero.

    Args:
        date: The time to say; the current UTC+3 time by default.

    Returns:
        The time, such as `"الساعة 3 و 5 دقيقة مساءً"`.
    """
    if date is None:
        date = date_utc_3()

    period = "صباحًا" if date.hour < 12 else "مساءً"
    hours = date.hour % 12 or 12
    result = f"الساعة {hours} "

    if date.minute > 0:
        result += f"و {date.minute} دقيقة "

    if date.second > 0:
        result += f"و {date.second} ثانية "

    return result + period


__all__ = (
    "stamp_to_date",
    "date_to_stamp",
    "date_utc_3",
    "date_utc",
    "time_utc_3",
    "time_utc",
    "arabic_time",
)
