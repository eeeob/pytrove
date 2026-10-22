from __future__ import annotations as _annotations

import random
from typing import TYPE_CHECKING

from pytrove.num_tools import jitter, randomness

if TYPE_CHECKING:
    import pytest


def test_jitter_stays_inside_the_window() -> None:
    rng = random.Random(0)
    for _ in range(2000):
        v = jitter(100, 0.1, 0.2, rng=rng)
        assert 90.0 <= v <= 120.0


def test_jitter_orders_the_window_for_a_negative_value() -> None:
    rng = random.Random(1)
    for _ in range(500):
        v = jitter(-100, 0.1, 0.2, rng=rng)
        assert -120.0 <= v <= -90.0


def test_jitter_degenerate_window_returns_the_value() -> None:
    assert jitter(50, 0.0, 0.0) == 50.0


def test_jitter_bias_tilts_the_mean() -> None:
    n = 4000
    low_bias = sum(jitter(100, 0.1, 0.1, bias=0.0, rng=random.Random(s)) for s in range(n)) / n
    high_bias = sum(jitter(100, 0.1, 0.1, bias=1.0, rng=random.Random(s)) for s in range(n)) / n

    assert low_bias < 100.0 < high_bias
    assert high_bias - low_bias > 4.0  # the two peaks pull the means well apart


def test_jitter_clamps_an_out_of_range_bias() -> None:
    rng = random.Random(1)
    low = [jitter(100, 0.1, 0.1, bias=-5, rng=rng) for _ in range(200)]
    high = [jitter(100, 0.1, 0.1, bias=5, rng=rng) for _ in range(200)]
    assert all(90 <= v <= 110 for v in low + high)
    assert sum(low) < sum(high)


def test_jitter_keeps_min_distance_from_previous() -> None:
    rng = random.Random(7)
    previous = 100.0
    for _ in range(3000):
        v = jitter(100, 0.3, 0.3, previous=previous, min_distance=5.0, rng=rng)
        assert abs(v - previous) >= 5.0 - 1e-9
        assert 70.0 <= v <= 130.0
        previous = v


def test_jitter_impossible_gap_returns_the_far_endpoint() -> None:
    # window [95, 105], min_distance 50 -> nothing is far enough, so the end
    # furthest from `previous` comes back.
    assert jitter(100, 0.05, 0.05, previous=104.0, min_distance=50.0) == 95.0
    assert jitter(100, 0.05, 0.05, previous=96.0, min_distance=50.0) == 105.0


def test_jitter_draws_from_the_one_remaining_side() -> None:
    rng = random.Random(5)
    # The band [100, 150] leaves only [90, 100): every draw lands there.
    assert all(90.0 <= jitter(100, 0.1, 0.1, previous=125.0, min_distance=25.0, rng=rng) < 100.0 for _ in range(300))
    # The band [50, 100] leaves only (100, 110].
    assert all(100.0 < jitter(100, 0.1, 0.1, previous=75.0, min_distance=25.0, rng=rng) <= 110.0 for _ in range(300))


def test_jitter_hole_outside_the_window_is_ignored() -> None:
    rng = random.Random(3)
    for _ in range(500):
        v = jitter(100, 0.1, 0.1, previous=10_000.0, min_distance=5.0, rng=rng)
        assert 90.0 <= v <= 110.0


def test_jitter_rng_makes_it_reproducible() -> None:
    a = [jitter(100, 0.1, 0.2, previous=99.0, min_distance=2.0, rng=random.Random(42)) for _ in range(5)]
    b = [jitter(100, 0.1, 0.2, previous=99.0, min_distance=2.0, rng=random.Random(42)) for _ in range(5)]
    assert a == b


def test_jitter_falls_back_to_the_spans_when_both_tails_carry_no_mass(monkeypatch: pytest.MonkeyPatch) -> None:
    # Window [90, 110] cut to the tails [90, 95] and [105, 110]; a flat CDF
    # gives both tails zero mass, so the pick goes by their widths and the
    # picked tail's midpoint comes back.
    monkeypatch.setattr(randomness, "_tri_cdf", lambda x, low, high, mode: 0.0)
    seen = {jitter(100, 0.1, 0.1, previous=100.0, min_distance=5.0, rng=random.Random(s)) for s in range(50)}
    assert seen == {92.5, 107.5}
