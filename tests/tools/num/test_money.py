from __future__ import annotations as _annotations

import pytest

from pytrove.errors import ValidationError
from pytrove.num_tools import apply_discount, reverse_discount


def test_apply_and_reverse_discount_roundtrip() -> None:
    price = 100.0
    discounted = apply_discount(price, 20)
    assert discounted == 80.0
    original = reverse_discount(discounted, 20)
    assert round(original, 2) == 100.0


def test_discount_bounds_are_validated() -> None:
    with pytest.raises(ValidationError):
        apply_discount(100, 101)

    with pytest.raises(ValidationError):
        reverse_discount(100, 100)

    with pytest.raises(ValidationError):
        reverse_discount(100, -1)


def test_discount_rounding() -> None:
    assert apply_discount(10, 33.333, ndigits=2) == 6.67
    assert reverse_discount(80, 20) == 100.0


def test_discount_rounds_to_an_int_for_none_digits() -> None:
    assert apply_discount(10, 33.333, ndigits=None) == 7
    assert isinstance(apply_discount(10, 33.333, ndigits=None), int)
    assert reverse_discount(7, 30, ndigits=None) == 10


@pytest.mark.parametrize(("discount", "expected"), [(0, 100.0), (100, 0.0), (50, 50.0)])
def test_apply_discount_at_its_bounds(discount: float, expected: float) -> None:
    assert apply_discount(100, discount) == expected


@pytest.mark.parametrize("discount", [-1, -50, 100.01])
def test_apply_discount_refuses_a_discount_outside_0_to_100(discount: float) -> None:
    with pytest.raises(ValidationError, match="between 0 and 100"):
        apply_discount(100, discount)


def test_reverse_discount_of_zero_is_the_identity() -> None:
    assert reverse_discount(80, 0) == 80.0


def test_discount_with_digits_returns_a_float() -> None:
    assert isinstance(apply_discount(10, 50), float)
    assert isinstance(reverse_discount(10, 50), float)
