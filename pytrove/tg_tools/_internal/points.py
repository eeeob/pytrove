"""Known (user id, creation date) points and id blocks for estimating when an account was made."""

from __future__ import annotations as _annotations

from bisect import bisect_right
from functools import cache
from typing import cast

from ...constants import TG_ACCOUNT_BLOCKS_FILE, TG_ACCOUNT_POINTS_FILE
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
def _blocks() -> tuple[tuple[int, float], ...]:
    """Load the bundled randomized id blocks on first use, then reuse them.

    A block closes when the next one opens, so only its lowest id and its
    opening are kept; the last block is still open.

    Returns:
        `(lowest id, opening timestamp)` pairs, both strictly increasing.
    """
    # `read_json` returns any `JsonValue`; the bundled file is a list of `[low, high,
    # "YYYY-MM-DD"]` rows (checked by its tests), so the cast states that shape for unpacking.
    rows = cast("list[tuple[int, int, str]]", read_json(TG_ACCOUNT_BLOCKS_FILE))
    return tuple((low, float(date_to_stamp(day, format="%Y-%m-%d"))) for low, _high, day in rows)


@cache
def _points() -> tuple[tuple[int, float], ...]:
    """Load the bundled points below the first block on first use, then reuse them.

    The bundled ids do not always grow with the date (many consecutive
    pairs go down), so the points are sorted by id, points sharing an id are merged,
    and the timestamps are fitted by `_monotone_fit` to never decrease.

    Points inside the blocks are left out: an id there carries no date of its
    own. Every id below the first block was handed out before it opened, so the
    fit is capped at that opening, and the first block's lowest id is added as
    the last point, dated by that opening.

    Returns:
        `(user id, creation timestamp)` pairs, ids strictly increasing and
        timestamps never decreasing; the last one is the first block's start.
    """
    first_low, first_opened = _blocks()[0]
    # `read_json` returns any `JsonValue`; the bundled file is a list of `[id, "YYYY-MM-DD"]`
    # pairs (checked by its tests), so the cast states that fixed shape for unpacking.
    rows = cast("list[tuple[int, str]]", read_json(TG_ACCOUNT_POINTS_FILE))
    by_id: dict[int, list[float]] = {}

    for uid, day in rows:
        if uid < first_low:
            by_id.setdefault(uid, []).append(date_to_stamp(day, format="%Y-%m-%d"))

    ids = sorted(by_id)
    fitted = _monotone_fit([sum(by_id[uid]) / len(by_id[uid]) for uid in ids])
    stamps = [min(stamp, first_opened) for stamp in fitted]
    return (*zip(ids, stamps, strict=True), (first_low, first_opened))


def _block_time(uid: int) -> float:
    """Estimate the creation time of an id inside a randomized block.

    Inside a block an id says only which block it is in, so the estimate is
    the middle of the block's window: from its opening to the next block's
    opening, or to now while it is the last one open.

    Args:
        uid: The user id, at or above the first block's lowest id.

    Returns:
        The middle of the block's window, as a Unix timestamp.
    """
    blocks = _blocks()
    # ponytail: an id past the last block's high bound counts as part of it, since
    # no newer block is known; the generator adds the next one once LyAdminBot does.
    index = bisect_right(blocks, (uid, float("inf"))) - 1
    opened = blocks[index][1]
    closed = blocks[index + 1][1] if index + 1 < len(blocks) else max(time_utc(), opened)
    return (opened + closed) / 2


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
    "_block_time",
    "_blocks",
    "_interpolate_time",
    "_points",
)
