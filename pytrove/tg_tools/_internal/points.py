"""Known (user id, creation date) points for estimating when an account was made."""

from __future__ import annotations as _annotations

from functools import cache
from pathlib import Path
from typing import Final

from ...date_tools import date_to_stamp, time_utc
from ...files_tools import load_json

_POINTS_FILE: Final[Path] = Path(__file__).parents[2] / "data" / "tg_points.json"
"""Bundled `[user id, "YYYY-MM-DD"]` pairs, ascending; read on first use only."""


@cache
def _points() -> tuple[tuple[int, float], ...]:
    """Load the bundled points on first use, then reuse them.

    Returns:
        `(user id, creation timestamp)` pairs, ascending.
    """
    return tuple((uid, date_to_stamp(day, format="%Y-%m-%d")) for uid, day in load_json(_POINTS_FILE))


def _interpolate_time(uid: int, id1: int, t1: float, id2: int, t2: float) -> float:
    """Estimate a user id's creation time on the line between two known points.

    Args:
        uid: The user id.
        id1: The first point's id.
        t1: The first point's timestamp.
        id2: The second point's id.
        t2: The second point's timestamp.

    Returns:
        The estimate, never later than now.
    """
    if id1 == id2:
        return t1

    return min(t1 + (t2 - t1) * (uid - id1) / (id2 - id1), time_utc())


__all__ = (
    "_interpolate_time",
    "_points",
    "_POINTS_FILE",
)
