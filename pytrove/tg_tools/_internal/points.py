"""Known (user id, creation date) points for estimating when an account was made."""

from __future__ import annotations as _annotations

from functools import cache
from typing import cast

from ...constants import TG_ACCOUNT_POINTS_FILE
from ...date_tools import date_to_stamp, time_utc
from ...files_tools import read_json


def _monotone_fit(values: list[float]) -> list[float]:
    """Fit the closest non-decreasing sequence to `values` (pool-adjacent-violators).

    Every run that goes down is replaced by its mean, merged with the runs
    before it until the sequence never decreases; the squared error is the
    smallest any non-decreasing sequence reaches.

    Args:
        values: The values, in order.

    Returns:
        The fitted values, one per input.

    Example:
        >>> _monotone_fit([1.0, 3.0, 2.0, 4.0])
        [1.0, 2.5, 2.5, 4.0]
    """
    blocks: list[tuple[float, int]] = []  # (sum, count) of each pooled run

    for value in values:
        total, count = value, 1

        while blocks and blocks[-1][0] / blocks[-1][1] > total / count:
            prev_total, prev_count = blocks.pop()
            total, count = total + prev_total, count + prev_count

        blocks.append((total, count))

    return [total / count for total, count in blocks for _ in range(count)]


@cache
def _points() -> tuple[tuple[int, float], ...]:
    """Load the bundled points on first use, then reuse them.

    The bundled ids do not always grow with the date (many consecutive
    pairs go down), so the points are sorted by id, points sharing an id are merged,
    and the timestamps are fitted by `_monotone_fit` to never decrease.

    Returns:
        `(user id, creation timestamp)` pairs, ids strictly increasing and
        timestamps never decreasing.
    """
    # `read_json` returns any `JsonValue`; the bundled file is a list of `[id, "YYYY-MM-DD"]`
    # pairs (checked by its tests), so the cast states that fixed shape for unpacking.
    rows = cast("list[tuple[int, str]]", read_json(TG_ACCOUNT_POINTS_FILE))
    by_id: dict[int, list[float]] = {}

    for uid, day in rows:
        by_id.setdefault(uid, []).append(date_to_stamp(day, format="%Y-%m-%d"))

    ids = sorted(by_id)
    stamps = _monotone_fit([sum(by_id[uid]) / len(by_id[uid]) for uid in ids])
    return tuple(zip(ids, stamps, strict=True))


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
)
