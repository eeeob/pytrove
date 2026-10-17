from __future__ import annotations as _annotations

import random

import pytest

from pytrove._internal._triangular import _tri_cdf, _tri_icdf


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
