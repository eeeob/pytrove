"""Generating random secrets."""

from __future__ import annotations as _annotations

import secrets
import string


def generate_secret(
    length: int,
    use_upper: bool = True,
    use_lower: bool = True,
    use_digits: bool = True,
    use_symbols: bool = True,
) -> str:
    """Generate a random secret with at least one character from each enabled set.

    Args:
        length: The secret's length.
        use_upper: Whether to use uppercase letters.
        use_lower: Whether to use lowercase letters.
        use_digits: Whether to use digits.
        use_symbols: Whether to use punctuation.

    Returns:
        The secret, drawn with `secrets`.

    Raises:
        ValueError: If `length` is not positive, no set is enabled, or `length`
            is shorter than the number of enabled sets.
    """
    if length <= 0:
        msg = "Password length must be greater than 0"
        raise ValueError(msg)

    sets = [
        chars for enabled, chars in (
            (use_lower, string.ascii_lowercase),
            (use_upper, string.ascii_uppercase),
            (use_digits, string.digits),
            (use_symbols, "!@#$%^&*()-_=+[]{};:,.<>?/"),
        ) if enabled
    ]

    if not sets:
        msg = "At least one character set must be enabled"
        raise ValueError(msg)

    if length < len(sets):
        msg = "Length too small for selected options"
        raise ValueError(msg)

    all_chars = "".join(sets)
    password = [secrets.choice(chars) for chars in sets]
    password += [secrets.choice(all_chars) for _ in range(length - len(sets))]
    secrets.SystemRandom().shuffle(password)
    return "".join(password)


__all__ = ("generate_secret",)
