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
