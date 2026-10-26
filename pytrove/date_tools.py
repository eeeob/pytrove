"""Timestamps, dates in UTC and UTC+3, and Arabic time display."""

from __future__ import annotations as _annotations

import math
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, overload

from .constants import TZ_UTC_PLUS_3
from .enums import TimeUnit

if TYPE_CHECKING:
    from datetime import time as time_of_day
    from datetime import tzinfo

    from .typings import Number, _False, _True


@overload
def stamp_to_date(
    stamp_time: Number,
    tz: tzinfo | None = timezone.utc,
    as_str: _False = False,
    keep_tzinfo: bool = False,
) -> datetime: ...
@overload
def stamp_to_date(
    stamp_time: Number, tz: tzinfo | None, as_str: _True, keep_tzinfo: bool = False
) -> str: ...
@overload
def stamp_to_date(
    stamp_time: Number,
    tz: tzinfo | None = timezone.utc,
    *,
    as_str: _True,
    keep_tzinfo: bool = False,
) -> str: ...
def stamp_to_date(
    stamp_time: Number,
    tz: tzinfo | None = timezone.utc,
    as_str: bool = False,
    keep_tzinfo: bool = False,
) -> datetime | str:
    """Turn a Unix timestamp into a date in a time zone.

    A fractional timestamp is floored: `-0.5` is the last second of 1969.

    Args:
        stamp_time: Seconds since the epoch.
        tz: The zone to express it in, any `tzinfo`; `None` for the machine's local
            zone, which always gives a naive local time.
        as_str: Whether to return `str(date)` instead of the `datetime`.
        keep_tzinfo: Whether to keep the zone and microseconds; otherwise both are
            dropped. With `tz=None` there is no zone, so it only keeps the microseconds.

    Returns:
        The date, or its string form.

    Raises:
        ValueError: If `stamp_time` is NaN, or (on some platforms) its year is
            outside 1-9999.
        OverflowError: If `stamp_time` does not fit the platform's `time_t`.
        OSError: If the platform's C library rejects `stamp_time`; on Windows, any
            value before the epoch with `tz=None`, or a year outside 1-9999.

    Example:
        >>> stamp_to_date(0)
        datetime.datetime(1970, 1, 1, 0, 0)
        >>> stamp_to_date(0, as_str=True)
        '1970-01-01 00:00:00'
        >>> stamp_to_date(0.5, keep_tzinfo=True)
        datetime.datetime(1970, 1, 1, 0, 0, 0, 500000, tzinfo=datetime.timezone.utc)
    """
    date = datetime.fromtimestamp(stamp_time, tz)

    if not keep_tzinfo:
        date = date.replace(tzinfo=None, microsecond=0)

    return str(date) if as_str else date


@overload
def date_to_stamp(
    date: str,
    tz: tzinfo | None = timezone.utc,
    format: str = "%d %b %Y, %H:%M",
    as_int: _True = True,
) -> int: ...
@overload
def date_to_stamp(date: str, tz: tzinfo | None, format: str, as_int: _False) -> float: ...
@overload
def date_to_stamp(
    date: str,
    tz: tzinfo | None = timezone.utc,
    format: str = "%d %b %Y, %H:%M",
    *,
    as_int: _False,
) -> float: ...
def date_to_stamp(
    date: str,
    tz: tzinfo | None = timezone.utc,
    format: str = "%d %b %Y, %H:%M",
    as_int: bool = True,
) -> int | float:
    """Turn a date string into a Unix timestamp.

    Args:
        date: The date text.
        tz: The zone a date without one is read in, any `tzinfo`; `None` for local
            time. A zone in `date` itself (`%z`) always wins.
        format: The `strptime` format of `date`. Month and day names (`%b`, `%a`)
            and `%p`, the default's `%b` included, follow the current `LC_TIME`
            locale, so the default reads English names only under the C or an
            English locale.
        as_int: Whether to floor the timestamp to whole seconds, as
            `stamp_to_date` does.

    Returns:
        Seconds since the epoch.

    Raises:
        ValueError: If `date` does not match `format`, a name in it included that
            the current locale spells differently.
        OverflowError: If the local time (`tz=None`) does not fit the platform's
            `time_t`.
        OSError: If the platform's C library rejects the local time (`tz=None`);
            on Windows, any value before the epoch.

    Example:
        >>> date_to_stamp("1 Jan 2020, 00:00")
        1577836800
        >>> date_to_stamp("2020-01-01", format="%Y-%m-%d", as_int=False)
        1577836800.0
    """
    dt = datetime.strptime(date, format)

    if dt.tzinfo is None and tz is not None:
        dt = dt.replace(tzinfo=tz)

    stamp_time = dt.timestamp()
    return math.floor(stamp_time) if as_int else stamp_time


@overload
def date_utc_3(as_str: _False = False, keep_tzinfo: bool = False) -> datetime: ...
@overload
def date_utc_3(as_str: _True, keep_tzinfo: bool = False) -> str: ...
def date_utc_3(as_str: bool = False, keep_tzinfo: bool = False) -> datetime | str:
    """Return the current date and time in UTC+3.

    Args:
        as_str: Whether to return `str(date)` instead of the `datetime`.
        keep_tzinfo: Whether to keep the zone and microseconds.

    Returns:
        The current date in UTC+3, or its string form.
    """
    return stamp_to_date(time.time(), TZ_UTC_PLUS_3, as_str, keep_tzinfo)


@overload
def date_utc(as_str: _False = False, keep_tzinfo: bool = False) -> datetime: ...
@overload
def date_utc(as_str: _True, keep_tzinfo: bool = False) -> str: ...
def date_utc(as_str: bool = False, keep_tzinfo: bool = False) -> datetime | str:
    """Return the current date and time in UTC.

    Args:
        as_str: Whether to return `str(date)` instead of the `datetime`.
        keep_tzinfo: Whether to keep the zone and microseconds.

    Returns:
        The current date in UTC, or its string form.
    """
    return stamp_to_date(time.time(), timezone.utc, as_str, keep_tzinfo)


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


def arabic_time(date: datetime | time_of_day | None = None) -> str:
    """Say a time of day in Arabic, on a 12-hour clock.

    Minutes and seconds are mentioned only when not zero; microseconds and any
    zone are ignored, so an aware value is said in its own wall time.

    Args:
        date: The `datetime` or `time` to say; the current UTC+3 time by default.

    Returns:
        The time, such as `"الساعة 3 و 5 دقيقة مساءً"`.

    Example:
        >>> arabic_time(datetime(2024, 1, 1, 15, 5))
        'الساعة 3 و 5 دقيقة مساءً'
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
