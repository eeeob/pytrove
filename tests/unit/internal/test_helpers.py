from __future__ import annotations as _annotations

import asyncio
import os
import random

import pytest

import pytrove._internal
from pytrove._internal._asyncio import _get_running_loop
from pytrove._internal._exceptions import _HARD_PROPAGATE
from pytrove._internal._fs import _COPY_BUF
from pytrove._internal._stability import _default_stability_check, _STABILITY_MIN_SIZE
from pytrove._internal._triangular import _tri_cdf, _tri_icdf


def _stat_of_size(size: int) -> os.stat_result:
    """Build a real `os.stat_result` whose only meaningful field is `st_size`."""
    fields = [0] * 10
    fields[6] = size
    return os.stat_result(fields)


def test_internal_package_exports_nothing() -> None:
    assert pytrove._internal.__all__ == ()


def test_hard_propagate_is_exactly_system_exit_and_keyboard_interrupt() -> None:
    assert _HARD_PROPAGATE == (SystemExit, KeyboardInterrupt)


def test_copy_buf_is_one_mebibyte() -> None:
    assert _COPY_BUF == 1 << 20


def test_get_running_loop_is_none_outside_a_loop() -> None:
    assert _get_running_loop() is None


async def test_get_running_loop_returns_the_current_loop_inside_one() -> None:
    assert _get_running_loop() is asyncio.get_running_loop()


def test_stability_min_size_is_one_mebibyte() -> None:
    assert _STABILITY_MIN_SIZE == 1 << 20


@pytest.mark.parametrize(("size", "guarded"), [
    (0, False),
    (_STABILITY_MIN_SIZE - 1, False),
    (_STABILITY_MIN_SIZE, True),
    (_STABILITY_MIN_SIZE * 4, True),
])
def test_default_stability_check_guards_only_files_at_least_the_minimum_size(size: int, guarded: bool) -> None:
    assert _default_stability_check(_stat_of_size(size), "ignored/path") is guarded


@pytest.mark.parametrize(("x", "expected"), [(-1.0, 0.0), (0.0, 0.0), (10.0, 1.0), (11.0, 1.0)])
def test_tri_cdf_is_clamped_outside_the_support(x: float, expected: float) -> None:
    assert _tri_cdf(x, 0.0, 10.0, 5.0) == expected


def test_tri_cdf_is_one_half_at_a_symmetric_mode() -> None:
    assert _tri_cdf(5.0, 0.0, 10.0, 5.0) == pytest.approx(0.5)


@pytest.mark.parametrize("mode", [0.0, 10.0])
def test_tri_cdf_handles_a_mode_at_either_end(mode: float) -> None:
    assert 0.0 < _tri_cdf(5.0, 0.0, 10.0, mode) < 1.0


@pytest.mark.parametrize("mode", [0.0, 3.0, 5.0, 10.0])
def test_tri_icdf_inverts_tri_cdf(mode: float) -> None:
    for u in (0.0, 0.1, 0.5, 0.9, 1.0):
        x = _tri_icdf(u, 0.0, 10.0, mode)
        assert _tri_cdf(x, 0.0, 10.0, mode) == pytest.approx(u, abs=1e-9)


def test_tri_icdf_returns_low_for_an_empty_support() -> None:
    assert _tri_icdf(0.7, 3.0, 3.0, 3.0) == 3.0


def test_tri_icdf_maps_uniform_draws_inside_the_support() -> None:
    rng = random.Random(7)
    assert all(0.0 <= _tri_icdf(rng.random(), 0.0, 10.0, 2.0) <= 10.0 for _ in range(1000))
