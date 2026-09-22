from __future__ import annotations as _annotations

from typing import overload
from datetime import datetime, timezone, timedelta

from .typings import _False, _True, Number

import time




@overload
def stamp_to_date(
    stamp_time: Number, #utc
    tz: timezone | None = ...,
    as_str: _False = ...,
    with_tzinfo: bool = ...
) -> datetime: ...
@overload
def stamp_to_date(
    stamp_time: Number,
    tz: timezone | None = ...,
    as_str: _True = ...,
    with_tzinfo: bool = ...
) -> str: ...
def stamp_to_date(
    stamp_time: Number,
    tz: timezone | None = timezone.utc,
    as_str: bool = False,
    with_tzinfo: bool = False
    ):

    date = datetime.fromtimestamp(stamp_time, tz)

    if not with_tzinfo:
        date = date.replace(tzinfo=None, microsecond=0)

    return str(date) if as_str else date


@overload
def date_to_stamp(
    date: str,
    tz: timezone | None = ...,
    format: str = ...,
    as_int: _True = ...
) -> int: ...
@overload
def date_to_stamp(
    date: str,
    tz: timezone | None = ...,
    format: str = ...,
    as_int: _False = ...
) -> float: ...
def date_to_stamp(
    date: str,
    tz: timezone | None = timezone.utc,
    format: str = "%d %b %Y, %H:%M",
    as_int: bool = True
    ):
    
    dt = datetime.strptime(date, format)

    if dt.tzinfo is None and tz is not None:
        dt = dt.replace(tzinfo=tz)

    return int(dt.timestamp()) if as_int else dt.timestamp()


@overload
def date_utc_3(
    as_str: _False = ...,
    with_tzinfo: bool = ...
) -> datetime: ...
@overload
def date_utc_3(
    as_str: _True = ...,
    with_tzinfo: bool = ...
) -> str: ...
def date_utc_3(
    as_str: bool = False,
    with_tzinfo: bool = False
    ):

    date = datetime.now(timezone.utc) + timedelta(hours=3)

    if not with_tzinfo:
        date = date.replace(tzinfo=None, microsecond=0)

    return str(date) if as_str else date


@overload
def date_utc(
    as_str: _False = ...,
    with_tzinfo: bool = ...
) -> datetime: ...
@overload
def date_utc(
    as_str: _True = ...,
    with_tzinfo: bool = ...
) -> str: ...
def date_utc(
    as_str: bool = False,
    with_tzinfo: bool = False
    ):

    date = datetime.now(timezone.utc)

    if not with_tzinfo:
        date = date.replace(tzinfo=None, microsecond=0)

    return str(date) if as_str else date


@overload
def time_utc_3() -> float: ...
@overload
def time_utc_3(as_int: _True) -> int: ...
def time_utc_3(as_int: bool = False):
    stamp_time = time.time() + 60 * 60 * 3
    return int(stamp_time) if as_int else stamp_time


@overload
def time_utc() -> float: ...
@overload
def time_utc(as_int: _True) -> int: ...
def time_utc(as_int: bool = False):
    stamp_time = time.time()
    return int(stamp_time) if as_int else stamp_time



def arabic_time(date: datetime | None = None) -> str:
    if date is None:
        date = date_utc_3()

    hours = date.hour
    minutes = date.minute
    seconds = date.second

    period = "صباحًا" if hours < 12 else "مساءً"
    hours = hours % 12
    hours = 12 if hours == 0 else hours

    result = f"الساعة {hours} "

    if minutes > 0:
        result += f"و {minutes} دقيقة "

    if seconds > 0:
        result += f"و {seconds} ثانية "

    result += f"{period}"

    return result



__all__ = [
    "stamp_to_date",
    "date_to_stamp",
    "date_utc_3",
    "date_utc",
    "time_utc_3",
    "time_utc",
    "arabic_time", 
]