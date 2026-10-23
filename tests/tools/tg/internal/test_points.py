from __future__ import annotations as _annotations

import json
import subprocess
import sys
import time

from pytrove.tg_tools._internal import points

LAZY_PROBE = """
import pytrove
from pytrove.tg_tools._internal import points
assert points._points.cache_info().currsize == 0
pytrove.tg_account_created_at(1)
assert points._points.cache_info().currsize == 1
"""


def test_bundled_points_are_read_on_first_use_and_not_at_import() -> None:
    subprocess.run([sys.executable, "-c", LAZY_PROBE], check=True)


def test_points_file_holds_id_and_date_pairs_in_date_order() -> None:
    rows = json.loads(points.TG_ACCOUNT_POINTS_FILE.read_text(encoding="utf-8"))
    assert rows and all(
        isinstance(uid, int) and time.strptime(day, "%Y-%m-%d") for uid, day in rows
    )
    assert [day for _, day in rows] == sorted(day for _, day in rows)
    assert all(isinstance(uid, int) and isinstance(stamp, int) for uid, stamp in points._points())


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
