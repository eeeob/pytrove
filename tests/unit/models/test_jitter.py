from __future__ import annotations as _annotations

import random

from pytrove.models import Jitter


def test_Jitter_defaults_to_plus_minus_ten_percent() -> None:
    j = Jitter(5, rng=random.Random(0))   # no decrease/increase given
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

    gaps = [abs(b - a) for a, b in zip(seq, seq[1:])]
    assert min(gaps) > 0.3             # no near-repeats, ever
    assert sum(gaps) / len(gaps) > 1.0  # and they genuinely range across [4, 7.5]


def test_Jitter_zero_wobble_is_the_rigid_golden_walk() -> None:
    a = Jitter(5, 0.2, 0.5, wobble=0.0, rng=random.Random(1))
    b = Jitter(5, 0.2, 0.5, wobble=0.0, rng=random.Random(1))
    assert [a() for _ in range(20)] == [b() for _ in range(20)]

    seq = [a() for _ in range(500)]
    gaps = [abs(y - x) for x, y in zip(seq, seq[1:])]
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
    assert sum(1 for v in low_vals if v < mid) / n > 0.55   # clearly leans low
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
    j.reset()
    assert j.last is None


def test_Jitter_value_can_be_moved_between_calls() -> None:
    j = Jitter(100, 0.1, 0.1, rng=random.Random(0))
    assert 90.0 <= j() <= 110.0

    j.value = 1000
    j.reset()
    assert 900.0 <= j() <= 1100.0
