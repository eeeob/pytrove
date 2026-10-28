from __future__ import annotations as _annotations

import random

import pytest

import math

from pytrove._internal._triangular import _clamp01, _tri_cdf, _tri_icdf, _tri_window


@pytest.mark.parametrize(("x", "expected"), [(-1.0, 0.0), (0.0, 0.0), (10.0, 1.0), (11.0, 1.0)])
def test_tri_cdf_is_clamped_outside_the_support(x: float, expected: float) -> None:
    assert _tri_cdf(x, 0.0, 10.0, 5.0) == expected


def test_tri_cdf_is_one_half_at_a_symmetric_mode() -> None:
    assert _tri_cdf(5.0, 0.0, 10.0, 5.0) == pytest.approx(0.5)


@pytest.mark.parametrize(("mode", "expected"), [(0.0, 0.75), (10.0, 0.25)])
def test_tri_cdf_handles_a_mode_at_either_end(mode: float, expected: float) -> None:
    assert _tri_cdf(5.0, 0.0, 10.0, mode) == pytest.approx(expected)


def test_tri_cdf_takes_the_exact_value_on_each_side_of_an_asymmetric_mode() -> None:
    assert _tri_cdf(2.0, 0.0, 10.0, 4.0) == pytest.approx(0.1)
    assert _tri_cdf(7.0, 0.0, 10.0, 4.0) == pytest.approx(1.0 - 9.0 / 60.0)


@pytest.mark.parametrize(("low", "high"), [(3.0, 3.0), (5.0, 2.0)])
def test_tri_cdf_is_a_point_mass_at_low_for_an_empty_or_negative_support(
    low: float, high: float
) -> None:
    assert _tri_cdf(low - 1.0, low, high, low) == 0.0
    assert _tri_cdf(low, low, high, low) == 1.0
    assert _tri_cdf(low + 1.0, low, high, low) == 1.0
    assert _tri_cdf(_tri_icdf(0.7, low, high, low), low, high, low) == 1.0


@pytest.mark.parametrize(
    ("u", "mode", "expected"),
    [
        (0.5, 5.0, 5.0),
        (0.25, 10.0, 5.0),
        (0.75, 0.0, 5.0),
        (0.1, 4.0, 2.0),
        (0.0, 4.0, 0.0),
        (1.0, 4.0, 10.0),
    ],
)
def test_tri_icdf_gives_the_exact_quantile(u: float, mode: float, expected: float) -> None:
    assert _tri_icdf(u, 0.0, 10.0, mode) == pytest.approx(expected)


@pytest.mark.parametrize(("u", "expected"), [(-0.5, 0.0), (1.5, 10.0), (math.nan, 0.0)])
def test_tri_icdf_clamps_u_outside_the_unit_interval(u: float, expected: float) -> None:
    assert _tri_icdf(u, 0.0, 10.0, 4.0) == expected


@pytest.mark.parametrize("mode", [0.0, 3.0, 5.0, 10.0])
def test_tri_icdf_inverts_tri_cdf(mode: float) -> None:
    for u in (0.0, 0.1, 0.5, 0.9, 1.0):
        x = _tri_icdf(u, 0.0, 10.0, mode)
        assert _tri_cdf(x, 0.0, 10.0, mode) == pytest.approx(u, abs=1e-9)


def test_tri_icdf_returns_low_for_an_empty_support() -> None:
    assert _tri_icdf(0.7, 3.0, 3.0, 3.0) == 3.0


def test_tri_icdf_returns_low_for_a_negative_support() -> None:
    assert _tri_icdf(0.7, 5.0, 2.0, 3.0) == 5.0


def test_tri_icdf_maps_uniform_draws_inside_the_support() -> None:
    rng = random.Random(7)
    assert all(0.0 <= _tri_icdf(rng.random(), 0.0, 10.0, 2.0) <= 10.0 for _ in range(1000))


@pytest.mark.parametrize(
    ("x", "expected"),
    [(-1.0, 0.0), (0.0, 0.0), (0.3, 0.3), (1.0, 1.0), (2.0, 1.0), (math.nan, 0.0), (math.inf, 1.0)],
)
def test_clamp01(x: float, expected: float) -> None:
    assert _clamp01(x) == expected


@pytest.mark.parametrize(
    ("args", "window"),
    [
        ((100.0, 0.1, 0.2, 0.5), (90.0, 120.0, 105.0)),
        ((100.0, 0.1, 0.2, 0.0), (90.0, 120.0, 90.0)),  # mode at the low end
        ((100.0, 0.1, 0.2, 1.0), (90.0, 120.0, 120.0)),  # mode at the high end
        ((100.0, 0.1, 0.2, -3.0), (90.0, 120.0, 90.0)),  # bias clamped up
        ((100.0, 0.1, 0.2, 7.0), (90.0, 120.0, 120.0)),  # bias clamped down
        ((100.0, 0.1, 0.2, math.nan), (90.0, 120.0, 90.0)),  # NaN bias reads as 0
        ((-10.0, 0.5, 0.5, 0.0), (-15.0, -5.0, -15.0)),  # ends swapped for a negative value
        ((100.0, -0.5, -0.5, 0.5), (50.0, 150.0, 100.0)),  # ends swapped for negative fractions
        ((7.0, 0.0, 0.0, 0.5), (7.0, 7.0, 7.0)),  # low == high: empty, mode at low
        ((0.0, 0.1, 0.1, 0.9), (0.0, 0.0, 0.0)),  # a zero value is empty too
    ],
)
def test_tri_window(
    args: tuple[float, float, float, float], window: tuple[float, float, float]
) -> None:
    assert _tri_window(*args) == pytest.approx(window)
