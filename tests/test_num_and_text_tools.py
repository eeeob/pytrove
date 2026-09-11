import random

from pytrove import to_int, to_int_deep, calc, apply_discount, reverse_discount, clean_spaces, to_str, split_part
from pytrove import jitter
from pytrove.models import Jitter


def test_to_int_basic():
    assert to_int("5") == 5
    assert to_int("5.5", as_int=False) == 5.5
    assert to_int("notanumber") == "notanumber"
    assert to_int("+123") == "+123"  # leading '+' is treated as non-numeric passthrough


def test_to_int_deep_converts_every_leaf():
    data = {"id": "123", "tags": ["1", "2.5", "x"], "meta": {"count": "10"}}
    assert to_int_deep(data) == {"id": 123, "tags": [1, 2.5, "x"], "meta": {"count": 10}}


def test_to_int_deep_converts_keys_too():
    assert to_int_deep({"1": "a", "2": "b"}) == {1: "a", 2: "b"}


def test_to_int_deep_walks_a_set():
    assert to_int_deep({"1", "2"}) == {1, 2}


def test_to_int_deep_preserves_container_type():
    result = to_int_deep(("1", "2", ["3"]))
    assert type(result) is tuple
    assert result == (1, 2, [3])


def test_to_int_deep_threads_as_int_to_every_leaf():
    # as_int=True is to_int's own -- a value with a "." only converts when
    # int() itself accepts it outright, same as to_int("3.0", as_int=True).
    assert to_int_deep(["3", "3.0"], as_int=True) == [3, "3.0"]
    assert to_int_deep(["3", "3.0"], as_int=False) == [3, 3.0]


def test_to_int_deep_leaves_a_plain_leaf_untouched():
    assert to_int_deep("notanumber") == "notanumber"
    assert to_int_deep(None) is None


def test_calc_basic_arithmetic():
    assert calc("2+2") == 4
    assert calc("10/2") == 5.0
    assert calc("2*3-1") == 5
    assert calc("-5+2") == -3
    assert calc("not math") == "not math"


def test_calc_long_compound_expressions_respect_operator_precedence():
    # calc()'s AST-based evaluator must match standard +-*/ precedence exactly,
    # the same as the eval() it replaced -- verified here against Python's own
    # operator precedence as ground truth.
    assert calc("2+3*4-5/2+10*3-7+1*2-3/3+4-5*6+7-8*9+10") == -45.5
    assert calc("1+2+3+4+5+6+7+8+9+10-1-2-3-4-5") == 40
    assert calc("2*3*4*5*6") == 720
    assert calc("-3.5+2*4-10/5+1.25*4") == 7.5
    assert calc("100-50+25-12.5+6.25-3.125") == 65.625
    assert calc("1*2*3*4*5*6*7*8*9*10") == 3628800


def test_calc_rejects_power_operator_dos_vector():
    # calc() must never evaluate "**" -- chained exponentiation like this can
    # exhaust memory/CPU. It should fail safe and return the original string.
    assert calc("9**9**9") == "9**9**9"


def test_calc_division_by_zero_falls_back_to_original_string():
    assert calc("1/0") == "1/0"


def test_calc_no_eval_side_channel():
    # Regression: calc() must never execute arbitrary code, even indirectly.
    assert calc("__import__('os')") == "__import__('os')"


def test_apply_and_reverse_discount_roundtrip():
    price = 100.0
    discounted = apply_discount(price, 20)
    assert discounted == 80.0
    original = reverse_discount(discounted, 20)
    assert round(original, 2) == 100.0


def test_clean_spaces():
    assert clean_spaces("a b\nc") == "abc"
    assert clean_spaces("a b\nc", with_lines=False) == "ab\nc"


def test_to_str():
    assert to_str(5) == "5"
    assert to_str(None) is None
    assert to_str([1, 2]) == [1, 2]


def test_split_part():
    assert split_part("a,b,c", ",", 1) == "b"
    assert split_part("a,b", ",", 5) == "a,b"  # out-of-range index falls back to original


# --- jitter / Jitter ---------------------------------------------------------

def test_jitter_stays_inside_the_window():
    rng = random.Random(0)
    for _ in range(2000):
        v = jitter(100, 0.1, 0.2, rng=rng)
        assert 90.0 <= v <= 120.0


def test_jitter_orders_the_window_for_a_negative_value():
    rng = random.Random(1)
    for _ in range(500):
        v = jitter(-100, 0.1, 0.2, rng=rng)
        assert -120.0 <= v <= -90.0


def test_jitter_degenerate_window_returns_the_value():
    assert jitter(50, 0.0, 0.0) == 50.0


def test_jitter_bias_tilts_the_mean():
    n = 4000
    low_bias = sum(jitter(100, 0.1, 0.1, bias=0.0, rng=random.Random(s)) for s in range(n)) / n
    high_bias = sum(jitter(100, 0.1, 0.1, bias=1.0, rng=random.Random(s)) for s in range(n)) / n

    assert low_bias < 100.0 < high_bias
    assert high_bias - low_bias > 4.0  # the two peaks pull the means well apart


def test_jitter_keeps_min_distance_from_previous():
    rng = random.Random(7)
    previous = 100.0
    for _ in range(3000):
        v = jitter(100, 0.3, 0.3, previous=previous, min_distance=5.0, rng=rng)
        assert abs(v - previous) >= 5.0 - 1e-9
        assert 70.0 <= v <= 130.0
        previous = v


def test_jitter_impossible_gap_returns_the_far_endpoint():
    # window [95, 105], min_distance 50 -> nothing is far enough, so the end
    # furthest from `previous` comes back.
    assert jitter(100, 0.05, 0.05, previous=104.0, min_distance=50.0) == 95.0
    assert jitter(100, 0.05, 0.05, previous=96.0, min_distance=50.0) == 105.0


def test_jitter_hole_outside_the_window_is_ignored():
    rng = random.Random(3)
    for _ in range(500):
        v = jitter(100, 0.1, 0.1, previous=10_000.0, min_distance=5.0, rng=rng)
        assert 90.0 <= v <= 110.0


def test_jitter_rng_makes_it_reproducible():
    a = [jitter(100, 0.1, 0.2, previous=99.0, min_distance=2.0, rng=random.Random(42)) for _ in range(5)]
    b = [jitter(100, 0.1, 0.2, previous=99.0, min_distance=2.0, rng=random.Random(42)) for _ in range(5)]
    assert a == b


def test_Jitter_defaults_to_plus_minus_ten_percent():
    j = Jitter(5, rng=random.Random(0))   # no decrease/increase given
    assert j.decrease == 0.1 and j.increase == 0.1
    for _ in range(1000):
        assert 4.5 <= j() <= 5.5


def test_Jitter_stays_inside_the_window_and_tracks_last():
    j = Jitter(5, 0.2, 0.5, rng=random.Random(11))

    assert j.last is None
    for _ in range(2000):
        v = j()
        assert 4.0 <= v <= 7.5
        assert j.last == v


def test_Jitter_spreads_consecutive_values_without_min_distance():
    # The user's exact case: jitter(5, 0.2, 0.5) in a loop clusters because
    # each draw is independent. Jitter walks the window instead, so the
    # closest any two consecutive values get is bounded well away from zero.
    j = Jitter(5, 0.2, 0.5, rng=random.Random(0))
    seq = [j() for _ in range(3000)]

    gaps = [abs(b - a) for a, b in zip(seq, seq[1:])]
    assert min(gaps) > 0.3             # no near-repeats, ever
    assert sum(gaps) / len(gaps) > 1.0  # and they genuinely range across [4, 7.5]


def test_Jitter_zero_wobble_is_the_rigid_golden_walk():
    a = Jitter(5, 0.2, 0.5, wobble=0.0, rng=random.Random(1))
    b = Jitter(5, 0.2, 0.5, wobble=0.0, rng=random.Random(1))
    assert [a() for _ in range(20)] == [b() for _ in range(20)]

    seq = [a() for _ in range(500)]
    gaps = [abs(y - x) for x, y in zip(seq, seq[1:])]
    assert min(gaps) > 0.5


def test_Jitter_min_distance_is_an_exact_hard_floor():
    j = Jitter(100, 0.3, 0.3, min_distance=5.0, rng=random.Random(11))
    prev = j()
    for _ in range(3000):
        nxt = j()
        assert abs(nxt - prev) >= 5.0 - 1e-9
        prev = nxt


def test_Jitter_bias_survives_a_tight_min_distance():
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


def test_Jitter_bias_still_tilts_the_stream():
    n = 4000
    lo = Jitter(100, 0.1, 0.1, bias=0.0, rng=random.Random(3))
    hi = Jitter(100, 0.1, 0.1, bias=1.0, rng=random.Random(3))
    mean_lo = sum(lo() for _ in range(n)) / n
    mean_hi = sum(hi() for _ in range(n)) / n
    assert mean_lo < 100.0 < mean_hi


def test_Jitter_reset_forgets_last_and_rephases():
    j = Jitter(100, 0.1, 0.1, min_distance=1.0, rng=random.Random(0))
    j()
    assert j.last is not None
    j.reset()
    assert j.last is None


def test_Jitter_value_can_be_moved_between_calls():
    j = Jitter(100, 0.1, 0.1, rng=random.Random(0))
    assert 90.0 <= j() <= 110.0

    j.value = 1000
    j.reset()
    assert 900.0 <= j() <= 1100.0
