from __future__ import annotations as _annotations

import string

import pytest

from pytrove.crypto_tools import generate_secret

_SYMBOLS = "!@#$%^&*()-_=+[]{};:,.<>?/"


def test_generate_secret_has_the_asked_length_and_one_of_each_enabled_set() -> None:
    secret = generate_secret(4)
    assert len(secret) == 4
    assert any(c in string.ascii_lowercase for c in secret)
    assert any(c in string.ascii_uppercase for c in secret)
    assert any(c in string.digits for c in secret)
    assert any(c in _SYMBOLS for c in secret)


def test_generate_secret_draws_only_from_the_enabled_sets() -> None:
    secret = generate_secret(32, use_upper=False, use_lower=False, use_symbols=False)
    assert len(secret) == 32
    assert set(secret) <= set(string.digits)

    assert set(generate_secret(32, use_digits=False, use_symbols=False)) <= set(
        string.ascii_letters
    )


def test_generate_secret_is_random() -> None:
    assert generate_secret(32) != generate_secret(32)


@pytest.mark.parametrize("length", [0, -1])
def test_generate_secret_rejects_a_non_positive_length(length: int) -> None:
    with pytest.raises(ValueError, match="greater than 0"):
        generate_secret(length)


def test_generate_secret_rejects_no_enabled_set() -> None:
    with pytest.raises(ValueError, match="At least one character set"):
        generate_secret(8, use_upper=False, use_lower=False, use_digits=False, use_symbols=False)


def test_generate_secret_rejects_a_length_below_the_number_of_sets() -> None:
    with pytest.raises(ValueError, match="too small"):
        generate_secret(3)

    assert len(generate_secret(1, use_upper=False, use_digits=False, use_symbols=False)) == 1
