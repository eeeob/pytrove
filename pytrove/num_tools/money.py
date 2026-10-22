"""Applying and reversing percentage discounts."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

from ..validate_tools import validation

if TYPE_CHECKING:
    from ..typings import Number


def apply_discount(price: Number, discount_percent: Number, ndigits: int | None = 4) -> float:
    """Take a percentage off a price.

    Args:
        price: The full price.
        discount_percent: The discount, from 0 to 100.
        ndigits: Digits to round to; `None` rounds to an int.

    Returns:
        The discounted price.

    Raises:
        ValidationError: If the discount is above 100.

    Example:
        >>> apply_discount(200, 15)
        170.0
        >>> apply_discount(99.99, 10, ndigits=None)
        90
    """
    validation(discount_percent <= 100, "discount_percent must be <= 100")
    return round(price * (1 - discount_percent / 100), ndigits)


def reverse_discount(discounted_price: Number, discount_percent: Number, ndigits: int | None = 4) -> float:
    """Recover the full price from a discounted one.

    Args:
        discounted_price: The price after the discount.
        discount_percent: The discount, from 0 up to but excluding 100.
        ndigits: Digits to round to; `None` rounds to an int.

    Returns:
        The price before the discount.

    Raises:
        ValidationError: If the discount is negative or 100 or more.

    Example:
        >>> reverse_discount(170, 15)
        200.0
    """
    validation(0 <= discount_percent < 100, "discount_percent must be between 0 and < 100")
    return round(discounted_price / (1 - discount_percent / 100), ndigits)


__all__ = (
    "apply_discount",
    "reverse_discount",
)
