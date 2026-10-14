import pytest

pytest.importorskip("cryptography")

from pytrove import encrypt, decrypt, d_encrypt, d_decrypt
from pytrove.errors import ValidationError


def test_encrypt_decrypt_roundtrip_bytes():
    data = b"secret payload"
    enc = encrypt(data, "password123")
    assert decrypt(enc, "password123") == data


def test_encrypt_decrypt_roundtrip_str():
    enc = encrypt("hello world", "password123")
    assert decrypt(enc, "password123") == b"hello world"


def test_decrypt_wrong_password_raises():
    enc = encrypt("hello", "correct-password")
    with pytest.raises(ValidationError):
        decrypt(enc, "wrong-password")


def test_decrypt_too_short_raises():
    with pytest.raises(ValidationError):
        decrypt(b"short", "password")


def test_decrypt_minimum_valid_length_boundary():
    # 16-byte salt + 12-byte nonce + 16-byte GCM tag = 44 bytes is the exact
    # floor for a valid (empty-plaintext) ciphertext; one byte less must
    # always be rejected before ever reaching AESGCM.decrypt().
    enc = encrypt(b"", "password123")
    assert len(enc) == 44
    assert decrypt(enc, "password123") == b""

    with pytest.raises(ValidationError):
        decrypt(enc[:-1], "password123")


def test_deterministic_encrypt_same_input_same_output():
    a = d_encrypt("same input", "password123")
    b = d_encrypt("same input", "password123")
    assert a == b  # deterministic by design (AES-SIV)
    assert d_decrypt(a, "password123") == b"same input"


def test_data_resolver_applied_on_decrypt():
    enc = encrypt("42", "password123")
    result = decrypt(enc, "password123", data_resolver=lambda b: int(b))
    assert result == 42
