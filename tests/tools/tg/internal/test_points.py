from __future__ import annotations as _annotations

import json
import subprocess
import sys
import time
from typing import TYPE_CHECKING

from pytrove.tg_tools._internal import points

if TYPE_CHECKING:
    import pytest

LAZY_PROBE = """
import pytrove
from pytrove.tg_tools._internal import points
assert points._points.cache_info().currsize == 0
assert points._blocks.cache_info().currsize == 0
pytrove.tg_account_created_at(1)
assert points._points.cache_info().currsize == 1
assert points._blocks.cache_info().currsize == 1
"""

DAY = 86_400


def test_bundled_points_and_blocks_are_read_on_first_use_and_not_at_import() -> None:
    subprocess.run([sys.executable, "-c", LAZY_PROBE], check=True)


def test_blocks_file_holds_back_to_back_ranges_opening_in_order() -> None:
    rows = json.loads(points.TG_ACCOUNT_BLOCKS_FILE.read_text(encoding="utf-8"))

    assert rows and all(
        isinstance(low, int)
        and isinstance(high, int)
        and low < high
        and time.strptime(day, "%Y-%m-%d")
        for low, high, day in rows
    )
    assert all(prev[1] == row[0] for prev, row in zip(rows, rows[1:], strict=False))
    assert [day for *_, day in rows] == sorted({day for *_, day in rows})


def test_blocks_are_loaded_once_as_lowest_ids_and_opening_stamps() -> None:
    rows = json.loads(points.TG_ACCOUNT_BLOCKS_FILE.read_text(encoding="utf-8"))
    loaded = points._blocks()

    assert loaded is points._blocks()
    assert loaded == tuple(
        (low, points.date_to_stamp(day, format="%Y-%m-%d")) for low, _, day in rows
    )


def test_points_file_holds_id_and_date_pairs_in_date_order() -> None:
    rows = json.loads(points.TG_ACCOUNT_POINTS_FILE.read_text(encoding="utf-8"))
    assert rows and all(
        isinstance(uid, int) and time.strptime(day, "%Y-%m-%d") for uid, day in rows
    )
    assert [day for _, day in rows] == sorted(day for _, day in rows)
    assert all(isinstance(uid, int) and isinstance(stamp, float) for uid, stamp in points._points())


def test_interpolate_time() -> None:
    assert points._interpolate_time(5, 0, 0.0, 10, 100.0) == 50.0
    assert points._interpolate_time(5, 3, 7.0, 3, 9.0) == 7.0
    assert points._interpolate_time(10**9, 0, 0.0, 1, 10**12) <= time.time()


def test_points_are_loaded_once_and_reused() -> None:
    assert points._points() is points._points()


def test_points_are_timestamps_in_date_order() -> None:
    loaded = points._points()

    assert len(loaded) >= 2
    assert [stamp for _, stamp in loaded] == sorted(stamp for _, stamp in loaded)


def test_interpolate_time_is_exact_at_both_ends() -> None:
    assert points._interpolate_time(0, 0, 10.0, 10, 20.0) == 10.0
    assert points._interpolate_time(10, 0, 10.0, 10, 20.0) == 20.0


def test_interpolate_time_extrapolates_past_the_second_point() -> None:
    assert points._interpolate_time(20, 0, 10.0, 10, 20.0) == 30.0


def test_points_have_strictly_increasing_ids() -> None:
    ids = [uid for uid, _ in points._points()]

    assert ids == sorted(set(ids))


def test_points_cover_every_id_below_the_first_block_and_end_at_its_opening() -> None:
    rows = json.loads(points.TG_ACCOUNT_POINTS_FILE.read_text(encoding="utf-8"))
    first_low, first_opened = points._blocks()[0]
    loaded = points._points()

    raw_stamps = [points.date_to_stamp(day, format="%Y-%m-%d") for _, day in rows]

    assert {uid for uid, _ in loaded} == {uid for uid, _ in rows if uid < first_low} | {first_low}
    assert loaded[-1] == (first_low, first_opened)
    assert all(min(raw_stamps) <= stamp <= first_opened for _, stamp in loaded)


def _with_blocks(monkeypatch: pytest.MonkeyPatch, *blocks: tuple[int, float]) -> None:
    monkeypatch.setattr(points, "_blocks", lambda: blocks)


def test_points_are_capped_at_the_first_blocks_opening(monkeypatch: pytest.MonkeyPatch) -> None:
    # An id below the first block dated after it opened (the source runs late)
    # would otherwise pull the line into the block era.
    rows = [[10, "2020-01-01"], [20, "2020-03-01"]]
    opened = points.date_to_stamp("2020-02-01", format="%Y-%m-%d")
    monkeypatch.setattr(points, "read_json", lambda path: rows)
    _with_blocks(monkeypatch, (30, opened))
    points._points.cache_clear()

    try:
        loaded = points._points()
    finally:
        points._points.cache_clear()

    assert loaded == ((10, opened - 31 * DAY), (20, opened), (30, opened))


def test_block_time_is_the_middle_of_a_closed_blocks_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_blocks(monkeypatch, (100, 1_000.0), (200, 3_000.0), (300, 7_000.0))

    assert points._block_time(100) == 2_000.0
    assert points._block_time(150) == 2_000.0
    assert points._block_time(199) == 2_000.0
    assert points._block_time(200) == 5_000.0


def test_block_time_of_the_open_block_runs_to_now(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_blocks(monkeypatch, (100, 1_000.0), (200, 3_000.0))
    monkeypatch.setattr(points, "time_utc", lambda: 9_000.0)

    assert points._block_time(200) == 6_000.0
    assert points._block_time(10**15) == 6_000.0  # past the last block: still the open one


def test_block_time_never_lands_before_an_opening_in_the_future(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_blocks(monkeypatch, (100, 5_000.0))
    monkeypatch.setattr(points, "time_utc", lambda: 1_000.0)

    assert points._block_time(100) == 5_000.0


def test_monotone_fit_pools_every_run_that_goes_down() -> None:
    assert points._monotone_fit([1.0, 3.0, 2.0, 4.0]) == [1.0, 2.5, 2.5, 4.0]
    assert points._monotone_fit([3.0, 2.0, 1.0]) == [2.0, 2.0, 2.0]
    assert points._monotone_fit([1.0, 2.0, 2.0, 5.0]) == [1.0, 2.0, 2.0, 5.0]
    assert points._monotone_fit([5.0, 1.0, 6.0, 2.0]) == [3.0, 3.0, 4.0, 4.0]
    assert points._monotone_fit([]) == []


def test_points_merge_a_repeated_id(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [[10, "2020-01-01"], [10, "2020-01-03"], [20, "2020-01-05"]]
    monkeypatch.setattr(points, "read_json", lambda path: rows)
    _with_blocks(monkeypatch, (30, points.date_to_stamp("2021-01-01", format="%Y-%m-%d")))
    points._points.cache_clear()

    try:
        loaded = points._points()
    finally:
        points._points.cache_clear()

    assert [uid for uid, _ in loaded] == [10, 20, 30]
    assert loaded[1][1] - loaded[0][1] == 3 * DAY
