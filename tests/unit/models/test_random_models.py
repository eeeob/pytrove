from __future__ import annotations as _annotations

import math
import random
from itertools import pairwise

import pytest

from pytrove._internal import _tri_cdf, _tri_window
from pytrove.models import Jitter
from pytrove.models._internal import _INV_PHI, _WOBBLE_SPREAD


def test_Jitter_defaults_to_plus_minus_ten_percent() -> None:
    j = Jitter(5, rng=random.Random(0))  # no decrease/increase given
    assert j.decrease == 0.1 and j.increase == 0.1
    for _ in range(1000):
        assert 4.5 <= j() <= 5.5


def test_Jitter_stays_inside_the_window_and_tracks_last() -> None:
    j = Jitter(5, 0.2, 0.5, rng=random.Random(11))

    assert j.last is None
    for _ in range(2000):
        v = j()
        assert 4.0 <= v <= 7.5
        assert j.last == v


def test_Jitter_spreads_consecutive_values_without_min_distance() -> None:
    # The user's exact case: jitter(5, 0.2, 0.5) in a loop clusters because
    # each draw is independent. Jitter walks the window instead, so the
    # closest any two consecutive values get is bounded well away from zero.
    j = Jitter(5, 0.2, 0.5, rng=random.Random(0))
    seq = [j() for _ in range(3000)]

    gaps = [abs(b - a) for a, b in pairwise(seq)]
    assert min(gaps) > 0.3  # no near-repeats, ever
    assert sum(gaps) / len(gaps) > 1.0  # and they genuinely range across [4, 7.5]


def test_Jitter_zero_wobble_is_the_rigid_golden_walk() -> None:
    a = Jitter(5, 0.2, 0.5, wobble=0.0, rng=random.Random(1))
    b = Jitter(5, 0.2, 0.5, wobble=0.0, rng=random.Random(1))
    assert [a() for _ in range(20)] == [b() for _ in range(20)]

    seq = [a() for _ in range(500)]
    gaps = [abs(y - x) for x, y in pairwise(seq)]
    assert min(gaps) > 0.5


def test_Jitter_min_distance_is_an_exact_hard_floor() -> None:
    j = Jitter(100, 0.3, 0.3, min_distance=5.0, rng=random.Random(11))
    prev = j()
    for _ in range(3000):
        nxt = j()
        assert abs(nxt - prev) >= 5.0 - 1e-9
        prev = nxt


def test_Jitter_bias_survives_a_tight_min_distance() -> None:
    # min_distance=1 on a width-3 window forces near-alternation; the bias
    # must still pull the stream low (mode at 0.3 of [4, 7] == 4.9).
    n = 6000
    low = Jitter(5, 0.2, 0.4, bias=0.1, min_distance=1.0, rng=random.Random(0))
    high = Jitter(5, 0.2, 0.4, bias=0.9, min_distance=1.0, rng=random.Random(0))

    low_vals = [low() for _ in range(n)]
    high_vals = [high() for _ in range(n)]

    mid = (4.0 + 7.0) / 2
    assert sum(low_vals) / n < mid < sum(high_vals) / n
    assert sum(1 for v in low_vals if v < mid) / n > 0.55  # clearly leans low
    # and the correction never washes the bias away toward symmetry
    assert sum(high_vals) / n - sum(low_vals) / n > 0.4


def test_Jitter_bias_still_tilts_the_stream() -> None:
    n = 4000
    lo = Jitter(100, 0.1, 0.1, bias=0.0, rng=random.Random(3))
    hi = Jitter(100, 0.1, 0.1, bias=1.0, rng=random.Random(3))
    mean_lo = sum(lo() for _ in range(n)) / n
    mean_hi = sum(hi() for _ in range(n)) / n
    assert mean_lo < 100.0 < mean_hi


def test_Jitter_reset_forgets_last_and_rephases() -> None:
    j = Jitter(100, 0.1, 0.1, min_distance=1.0, rng=random.Random(0))
    j()
    assert j.last is not None
    before = j._u
    j.reset()
    assert j.last is None and j._u != before


def test_Jitter_value_can_be_moved_between_calls() -> None:
    j = Jitter(100, 0.1, 0.1, rng=random.Random(0))
    assert 90.0 <= j() <= 110.0

    j.value = 1000
    j.reset()
    assert 900.0 <= j() <= 1100.0


def test_Jitter_swaps_the_ends_of_a_negative_window() -> None:
    j = Jitter(-5, rng=random.Random(0))
    for _ in range(200):
        assert -5.5 <= j() <= -4.5


def test_Jitter_zero_width_window_returns_its_single_point() -> None:
    j = Jitter(5, decrease=0, increase=0)
    assert j() == 5.0
    assert j.last == 5.0


def test_Jitter_clamps_bias_and_wobble_into_the_unit_range() -> None:
    def run(**kw: float) -> list[float]:
        """Return a seeded stream for these settings."""
        j = Jitter(5, rng=random.Random(3), **kw)
        return [j() for _ in range(50)]

    assert run(bias=-1.0) == run(bias=0.0)
    assert run(bias=2.0) == run(bias=1.0)
    assert run(wobble=-1.0) == run(wobble=0.0)
    assert run(wobble=5.0) == run(wobble=1.0)


def test_Jitter_min_distance_wider_than_the_window_takes_the_furthest_end() -> None:
    j = Jitter(5, min_distance=10.0, rng=random.Random(4))
    for _ in range(50):
        prev = j()
        nxt = j()
        far = 4.5 if (prev - 4.5) >= (5.5 - prev) else 5.5
        assert nxt == pytest.approx(far)


def _cdf_gap(a: float, b: float) -> float:
    """Return the wrapped distance between two CDF positions."""
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d)


def _aimed_at(j: Jitter, target: float) -> Jitter:
    """Set the walk so a `wobble=0` step lands on `target`, a value inside the window."""
    low, high, mode = _tri_window(j.value, j.decrease, j.increase, j.bias)
    j._u = (_tri_cdf(target, low, high, mode) - _INV_PHI) % 1.0
    return j


def test_Jitter_is_drawn_only_by_calling_it() -> None:
    assert not hasattr(Jitter, "next")


def test_Jitter_starts_at_a_random_phase_from_its_rng() -> None:
    assert Jitter(5, rng=random.Random(0))._u == random.Random(0).random()
    assert Jitter(5, rng=random.Random(0))._u != Jitter(5, rng=random.Random(1))._u


def test_Jitter_reset_draws_a_new_phase_from_its_rng() -> None:
    j = Jitter(5, wobble=0.0, rng=random.Random(0))  # a rigid step draws nothing
    j()
    j.reset()

    ref = random.Random(0)
    ref.random()
    assert j._u == ref.random()


def test_Jitter_without_rng_draws_from_the_random_module() -> None:
    state = random.getstate()
    try:
        random.seed(7)
        first = Jitter(5)
        a = [first() for _ in range(20)]
        random.seed(7)
        second = Jitter(5)
        b = [second() for _ in range(20)]
    finally:
        random.setstate(state)

    assert a == b and all(4.5 <= v <= 5.5 for v in a)


@pytest.mark.parametrize("min_distance", [0.0, 5.0])
def test_Jitter_value_moves_without_a_reset(min_distance: float) -> None:
    j = Jitter(100, min_distance=min_distance, rng=random.Random(0))
    for _ in range(20):
        assert 90.0 <= j() <= 110.0

    j.value = 1000
    prev = None
    for _ in range(200):
        v = j()
        assert 900.0 <= v <= 1100.0
        if prev is not None:
            assert abs(v - prev) >= min_distance - 1e-9
        prev = v


def test_Jitter_snaps_up_past_the_band_when_the_step_leans_up() -> None:
    j = _aimed_at(Jitter(5, 0.2, 0.4, wobble=0.0, min_distance=1.0, rng=random.Random(0)), 5.2)
    j.last = 5.0

    result = j()
    assert 6.0 <= result <= 7.0
    assert j._u == _tri_cdf(result, 4.0, 7.0, 5.5)


def test_Jitter_snaps_up_when_the_low_edge_is_outside_the_window() -> None:
    j = _aimed_at(Jitter(5, 0.2, 0.4, wobble=0.0, min_distance=1.0, rng=random.Random(0)), 4.3)
    j.last = 4.5  # the step leans down, but `4.5 - 1` is below the window

    result = j()
    assert 5.5 <= result <= 7.0
    assert j._u == _tri_cdf(result, 4.0, 7.0, 5.5)


def test_Jitter_snaps_down_when_the_high_edge_is_outside_the_window() -> None:
    j = _aimed_at(Jitter(5, 0.2, 0.4, wobble=0.0, min_distance=1.0, rng=random.Random(0)), 6.8)
    j.last = 6.5  # the step leans up, but `6.5 + 1` is above the window

    result = j()
    assert 4.0 <= result <= 5.5
    assert j._u == _tri_cdf(result, 4.0, 7.0, 5.5)


def test_Jitter_snaps_down_past_the_band_when_the_step_leans_down() -> None:
    j = _aimed_at(Jitter(5, 0.2, 0.4, wobble=0.0, min_distance=1.0, rng=random.Random(0)), 5.5)
    j.last = 6.0

    result = j()
    assert 4.0 <= result <= 5.0
    assert j._u == _tri_cdf(result, 4.0, 7.0, 5.5)


def test_Jitter_takes_the_furthest_end_when_the_window_is_narrower_than_twice_the_gap() -> None:
    # Width 3 is wider than the gap 2 but narrower than 4: from 5.3 neither
    # `5.3 +/- 2` is inside [4, 7], so the floor cannot hold.
    j = _aimed_at(Jitter(5, 0.2, 0.4, wobble=0.0, min_distance=2.0, rng=random.Random(0)), 5.0)
    j.last = 5.3

    assert j() == 7.0
    assert j._u == 1.0

    j = _aimed_at(Jitter(5, 0.2, 0.4, wobble=0.0, min_distance=2.0, rng=random.Random(0)), 6.0)
    j.last = 5.8
    assert j() == 4.0


def test_Jitter_zero_width_window_repeats_its_point_despite_min_distance() -> None:
    j = Jitter(5, decrease=0, increase=0, min_distance=1.0)
    assert [j() for _ in range(3)] == [5.0, 5.0, 5.0]


def test_Jitter_window_may_span_zero() -> None:
    j = Jitter(5, decrease=2.0, increase=0.1, rng=random.Random(0))
    values = [j() for _ in range(500)]
    assert all(-5.0 <= v <= 5.5 for v in values)
    assert min(values) < 0.0 < max(values)


def test_Jitter_consecutive_steps_keep_their_cdf_gap() -> None:
    j = Jitter(5, 0.2, 0.5, rng=random.Random(5))
    low, high, mode = _tri_window(5, 0.2, 0.5, 0.5)
    positions = [_tri_cdf(j(), low, high, mode) for _ in range(5000)]

    floor = 1.0 - _INV_PHI * (1.0 + _WOBBLE_SPREAD)
    assert min(_cdf_gap(a, b) for a, b in pairwise(positions)) >= floor - 1e-9


@pytest.mark.parametrize("bias", [0.2, 0.8])
def test_Jitter_keeps_the_triangular_shape_and_covers_the_window(bias: float) -> None:
    n = 20000
    j = Jitter(100, 0.2, 0.2, bias=bias, rng=random.Random(9))
    values = [j() for _ in range(n)]
    low, high, mode = _tri_window(100, 0.2, 0.2, bias)

    for x in (85.0, mode, 100.0, 115.0):
        share = sum(v <= x for v in values) / n
        assert share == pytest.approx(_tri_cdf(x, low, high, mode), abs=0.02)
    assert min(values) < low + 0.01 * (high - low)
    assert max(values) > high - 0.01 * (high - low)


def test_Jitter_compares_by_identity_and_hides_its_phase() -> None:
    j = Jitter(5)
    assert j == j and Jitter(5) != Jitter(5)
    assert "_u" not in repr(j)


def test_Jitter_reads_a_nan_bias_or_wobble_as_zero() -> None:
    def run(**kw: float) -> list[float]:
        """Return a seeded stream for these settings."""
        j = Jitter(5, rng=random.Random(3), **kw)
        return [j() for _ in range(50)]

    assert run(bias=math.nan) == run(bias=0.0)
    assert run(wobble=math.nan) == run(wobble=0.0)

    j = Jitter(5, wobble=math.nan, rng=random.Random(0))
    j()
    j.wobble = 1.0
    assert all(4.5 <= j() <= 5.5 for _ in range(20))
    assert not math.isnan(j._u)


def test_Jitter_decrease_moves_the_high_end_of_a_negative_window() -> None:
    j = Jitter(-10, decrease=0.5, increase=0.0, rng=random.Random(0))
    values = [j() for _ in range(2000)]
    assert all(-10.0 <= v <= -5.0 for v in values)
    assert max(values) > -5.5 and min(values) < -9.5  # reaches up to -5, not just -9
