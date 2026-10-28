from __future__ import annotations as _annotations

import string

import pytest

from pytrove.crypto_tools import generate_secret
from pytrove.crypto_tools.secret import _SYMBOLS


def test_symbols_are_the_documented_subset_of_punctuation() -> None:
    assert len(_SYMBOLS) == 26
    assert set(_SYMBOLS) <= set(string.punctuation)
    assert not set(_SYMBOLS) & set("~`'\"|\\")


def test_generate_secret_has_the_asked_length_and_one_of_each_enabled_set() -> None:
    secret = generate_secret(4)
    assert len(secret) == 4
    assert any(c in string.ascii_lowercase for c in secret)
    assert any(c in string.ascii_uppercase for c in secret)
    assert any(c in string.digits for c in secret)
    assert any(c in _SYMBOLS for c in secret)


@pytest.mark.parametrize(
    ("flag", "alphabet"),
    [
        ("use_upper", string.ascii_uppercase),
        ("use_lower", string.ascii_lowercase),
        ("use_digits", string.digits),
        ("use_symbols", _SYMBOLS),
    ],
)
def test_generate_secret_draws_from_a_single_set(flag: str, alphabet: str) -> None:
    flags = dict.fromkeys(("use_upper", "use_lower", "use_digits", "use_symbols"), False)
    flags[flag] = True
    secret = generate_secret(32, **flags)
    assert len(secret) == 32
    assert set(secret) <= set(alphabet)


def test_generate_secret_draws_only_from_the_enabled_sets() -> None:
    assert set(generate_secret(32, use_digits=False, use_symbols=False)) <= set(
        string.ascii_letters
    )


@pytest.mark.parametrize(
    ("kwargs", "alphabets"),
    [
        (
            {"use_digits": False, "use_symbols": False},
            (string.ascii_lowercase, string.ascii_uppercase),
        ),
        ({"use_upper": False}, (string.ascii_lowercase, string.digits, _SYMBOLS)),
    ],
)
def test_generate_secret_takes_one_of_each_subset_at_minimum_length(
    kwargs: dict[str, bool], alphabets: tuple[str, ...]
) -> None:
    for _ in range(50):
        secret = generate_secret(len(alphabets), **kwargs)
        assert sorted(next(i for i, a in enumerate(alphabets) if c in a) for c in secret) == list(
            range(len(alphabets))
        )


def test_generate_secret_is_random() -> None:
    assert generate_secret(32) != generate_secret(32)


@pytest.mark.parametrize("length", [0, -1])
def test_generate_secret_rejects_a_non_positive_length(length: int) -> None:
    with pytest.raises(ValueError, match="Secret length must be greater than 0"):
        generate_secret(length)


def test_generate_secret_rejects_a_non_integer_length() -> None:
    with pytest.raises(TypeError):
        generate_secret(4.5)


def test_generate_secret_rejects_no_enabled_set() -> None:
    with pytest.raises(ValueError, match="At least one character set"):
        generate_secret(8, use_upper=False, use_lower=False, use_digits=False, use_symbols=False)


def test_generate_secret_rejects_a_length_below_the_number_of_sets() -> None:
    with pytest.raises(ValueError, match="too small"):
        generate_secret(3)

    assert len(generate_secret(1, use_upper=False, use_digits=False, use_symbols=False)) == 1
