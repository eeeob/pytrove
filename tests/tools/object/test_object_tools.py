"""Tests of `crypto_tools.generate_secret` that still live here; they belong in `tests/tools/crypto/`."""

from __future__ import annotations as _annotations

import pytest

from pytrove import generate_secret


def test_generate_secret_length_and_charset() -> None:
    secret = generate_secret(16)
    assert len(secret) == 16


def test_generate_secret_rejects_non_positive_length() -> None:
    with pytest.raises(ValueError):
        generate_secret(0)


def test_generate_secret_rejects_no_charset() -> None:
    with pytest.raises(ValueError):
        generate_secret(8, use_upper=False, use_lower=False, use_digits=False, use_symbols=False)


def test_generate_secret_only_digits() -> None:
    secret = generate_secret(10, use_upper=False, use_lower=False, use_symbols=False)
    assert secret.isdigit()
    assert len(secret) == 10


def test_generate_secret_requires_room_for_each_set() -> None:
    with pytest.raises(ValueError, match="too small"):
        generate_secret(2)

    assert len(generate_secret(4)) == 4
