from __future__ import annotations as _annotations

from importlib.util import find_spec

import pytest

from pytrove import d_decrypt, d_encrypt, decrypt, encrypt
from pytrove.errors import ValidationError

_HAS_CRYPTO = find_spec("cryptography") is not None

needs_crypto = pytest.mark.skipif(not _HAS_CRYPTO, reason="needs the `crypto` extra")


@pytest.mark.skipif(_HAS_CRYPTO, reason="needs the `crypto` extra to be missing")
def test_ciphers_need_the_crypto_extra() -> None:
    with pytest.raises(ImportError, match=r"pytrove\[crypto\]"):
        encrypt(b"x", "pw")

    with pytest.raises(ImportError, match=r"pytrove\[crypto\]"):
        d_encrypt(b"x", "pw")


@needs_crypto
def test_encrypt_decrypt_roundtrip_bytes() -> None:
    data = b"secret payload"
    enc = encrypt(data, "password123")
    assert decrypt(enc, "password123") == data


@needs_crypto
def test_encrypt_decrypt_roundtrip_str() -> None:
    enc = encrypt("hello world", "password123")
    assert decrypt(enc, "password123") == b"hello world"


@needs_crypto
def test_decrypt_wrong_password_raises() -> None:
    enc = encrypt("hello", "correct-password")
    with pytest.raises(ValidationError):
        decrypt(enc, "wrong-password")


@needs_crypto
def test_decrypt_too_short_raises() -> None:
    with pytest.raises(ValidationError):
        decrypt(b"short", "password")


@needs_crypto
def test_decrypt_minimum_valid_length_boundary() -> None:
    # 16-byte salt + 12-byte nonce + 16-byte GCM tag = 44 bytes is the exact
    # floor for a valid (empty-plaintext) ciphertext; one byte less must
    # always be rejected before ever reaching `AESGCM.decrypt()`.
    enc = encrypt(b"", "password123")
    assert len(enc) == 44
    assert decrypt(enc, "password123") == b""

    with pytest.raises(ValidationError):
        decrypt(enc[:-1], "password123")


@needs_crypto
def test_deterministic_encrypt_same_input_same_output() -> None:
    a = d_encrypt("same input", "password123")
    b = d_encrypt("same input", "password123")
    assert a == b  # deterministic by design (AES-SIV)
    assert d_decrypt(a, "password123") == b"same input"


@needs_crypto
def test_data_resolver_applied_on_decrypt() -> None:
    enc = encrypt("42", "password123")
    result = decrypt(enc, "password123", data_resolver=int)
    assert result == 42


@needs_crypto
def test_d_decrypt_wrong_password_raises() -> None:
    with pytest.raises(ValidationError, match="Decryption failed"):
        d_decrypt(d_encrypt("secret", "right"), "wrong")


@needs_crypto
def test_d_decrypt_applies_the_resolver() -> None:
    assert d_decrypt(d_encrypt(b"x", "pw"), "pw", data_resolver=bytes.decode) == "x"
