from __future__ import annotations as _annotations

from importlib.util import find_spec
from typing import TYPE_CHECKING, Any

import pytest

from pytrove import d_decrypt, d_encrypt, decrypt, encrypt
from pytrove.errors import ValidationError

if TYPE_CHECKING:
    from collections.abc import Callable

_HAS_CRYPTO = find_spec("cryptography") is not None

needs_crypto = pytest.mark.skipif(not _HAS_CRYPTO, reason="needs the `crypto` extra")

# Known-answer vectors produced by the 200k-round PBKDF2-SHA256 layout; a change to the KDF,
# the salt or the ciphertext layout breaks every stored ciphertext and must fail here.
_KNOWN_PLAINTEXT = b"known plaintext"
_KNOWN_BLOB = bytes.fromhex(
    "77334722c87bf4613381e7f762f01a580245e4972297d73b8b21c79e"
    "3c89004a5a08113115d970aa74a0c47cfddedcfd03f5a04a93bedabf07bc5e"
)
_D_VECTORS = [
    (b"", "pw", "11e81c89b8683e04f299f46738283085"),
    (b"x", "pw", "d9c114dc638225d6b896645a2f65f9827c"),
    ("héllo ✓", "пароль", "7199f6465dd1e8b6baeae22fed4ab5d264552bbfc80da0843288"),
]


def _flip(blob: bytes, offset: int) -> bytes:
    """Return `blob` with the byte at `offset` inverted."""
    out = bytearray(blob)
    out[offset] ^= 0xFF
    return bytes(out)


def _invalid_tag() -> type[Exception]:
    """Return `cryptography`'s `InvalidTag`, imported only once the extra is known to exist."""
    from cryptography.exceptions import InvalidTag  # noqa: PLC0415 - optional: the `crypto` extra.

    return InvalidTag


@pytest.mark.skipif(_HAS_CRYPTO, reason="needs the `crypto` extra to be missing")
@pytest.mark.parametrize(
    ("func", "data"),
    [(encrypt, b"x"), (decrypt, b"x" * 44), (d_encrypt, b"x"), (d_decrypt, b"x" * 16)],
    ids=["encrypt", "decrypt", "d_encrypt", "d_decrypt"],
)
def test_ciphers_need_the_crypto_extra(func: Callable[[bytes, str], Any], data: bytes) -> None:
    with pytest.raises(ImportError, match=r"pytrove\[crypto\]"):
        func(data, "pw")


@needs_crypto
def test_decrypt_known_answer() -> None:
    assert decrypt(_KNOWN_BLOB, "pw") == _KNOWN_PLAINTEXT


@needs_crypto
@pytest.mark.parametrize(("data", "password", "expected"), _D_VECTORS)
def test_d_encrypt_known_answer(data: bytes | str, password: str, expected: str) -> None:
    assert d_encrypt(data, password).hex() == expected
    plain = data.encode() if isinstance(data, str) else data
    assert d_decrypt(bytes.fromhex(expected), password) == plain


@needs_crypto
def test_d_encrypt_known_answer_with_context() -> None:
    # Pins how `context` is mixed into the key; changing it breaks stored ciphertexts.
    expected = "afc11f89e0ea2d0165e7ffbca42f071689"
    assert d_encrypt(b"x", "pw", context=b"ctx").hex() == expected
    assert d_decrypt(bytes.fromhex(expected), "pw", context=b"ctx") == b"x"


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
def test_encrypt_decrypt_roundtrip_non_ascii_text_and_password() -> None:
    assert decrypt(encrypt("héllo ✓", "пароль"), "пароль") == "héllo ✓".encode()
    assert decrypt(encrypt("abc", "pw"), "pw") == decrypt(encrypt(b"abc", "pw"), "pw")


@needs_crypto
def test_encrypt_is_randomised_with_the_documented_layout() -> None:
    a = encrypt(b"abc", "pw")
    b = encrypt(b"abc", "pw")
    assert a != b
    assert a[:16] != b[:16]  # salt
    assert a[16:28] != b[16:28]  # nonce
    assert len(a) == 16 + 12 + 3 + 16


@needs_crypto
@pytest.mark.parametrize(
    "wrap", [bytes, bytearray, memoryview], ids=["bytes", "bytearray", "memoryview"]
)
def test_ciphers_accept_any_bytes_like_input(wrap: Callable[[bytes], Any]) -> None:
    assert decrypt(wrap(encrypt(wrap(b"x"), "pw")), "pw") == b"x"
    assert d_decrypt(wrap(d_encrypt(wrap(b"x"), "pw")), "pw") == b"x"


@needs_crypto
def test_decrypt_wrong_password_raises() -> None:
    enc = encrypt("hello", "correct-password")
    with pytest.raises(ValidationError, match="Decryption failed") as exc_info:
        decrypt(enc, "wrong-password")
    assert isinstance(exc_info.value.__cause__, _invalid_tag())


@needs_crypto
@pytest.mark.parametrize("size", [0, 5, 43])
def test_decrypt_rejects_data_shorter_than_the_layout(size: int) -> None:
    # 16-byte salt + 12-byte nonce + 16-byte GCM tag = 44 bytes is the floor; anything
    # shorter is rejected by the length guard, before `AESGCM.decrypt()` is reached.
    with pytest.raises(ValidationError, match="too short") as exc_info:
        decrypt(encrypt(b"", "pw")[:size], "pw")
    assert exc_info.value.__cause__ is None


@needs_crypto
def test_decrypt_minimum_valid_length_boundary() -> None:
    enc = encrypt(b"", "password123")
    assert len(enc) == 44
    assert decrypt(enc, "password123") == b""

    # 44 bytes pass the guard, so a forged blob of that size fails on the tag instead.
    with pytest.raises(ValidationError, match="Decryption failed") as exc_info:
        decrypt(bytes(44), "password123")
    assert isinstance(exc_info.value.__cause__, _invalid_tag())


@needs_crypto
@pytest.mark.parametrize("offset", [0, 16, 28, -1], ids=["salt", "nonce", "body", "tag"])
def test_decrypt_rejects_a_tampered_byte(offset: int) -> None:
    enc = encrypt(b"abc", "pw")
    with pytest.raises(ValidationError, match="Decryption failed") as exc_info:
        decrypt(_flip(enc, offset), "pw")
    assert isinstance(exc_info.value.__cause__, _invalid_tag())


@needs_crypto
@pytest.mark.parametrize(
    ("func", "data", "password", "error"),
    [
        (decrypt, "a" * 60, "pw", TypeError),
        (decrypt, "blob", b"pw", AttributeError),
        (decrypt, "blob", "\ud800", UnicodeEncodeError),
        (d_decrypt, "abc" * 10, "pw", TypeError),
        (d_decrypt, "d_blob", b"pw", AttributeError),
        (d_decrypt, "d_blob", "\ud800", UnicodeEncodeError),
    ],
)
def test_decrypt_misuse_propagates_the_original_error(
    func: Callable[[Any, Any], Any], data: str, password: Any, error: type[Exception]
) -> None:
    blobs = {"blob": encrypt(b"x", "pw"), "d_blob": d_encrypt(b"x", "pw")}
    with pytest.raises(error):
        func(blobs.get(data, data), password)


@needs_crypto
def test_deterministic_encrypt_same_input_same_output() -> None:
    a = d_encrypt("same input", "password123")
    b = d_encrypt("same input", "password123")
    assert a == b  # deterministic by design (AES-SIV)
    assert d_decrypt(a, "password123") == b"same input"


@needs_crypto
def test_d_encrypt_depends_on_text_password_and_plaintext() -> None:
    base = d_encrypt(b"abc", "pw")
    assert d_encrypt("abc", "pw") == base
    assert d_encrypt(b"abc", "other") != base
    assert d_encrypt(b"abd", "pw") != base
    assert len(base) == 3 + 16
    assert d_decrypt(d_encrypt(b"", "pw"), "pw") == b""


@needs_crypto
def test_d_encrypt_context_binds_the_ciphertext() -> None:
    base = d_encrypt(b"abc", "pw")
    assert d_encrypt(b"abc", "pw", context=b"") == base
    bound = d_encrypt(b"abc", "pw", context=b"users.email")
    assert bound != base
    assert bound != d_encrypt(b"abc", "pw", context=b"users.phone")
    assert d_decrypt(bound, "pw", context=b"users.email") == b"abc"

    with pytest.raises(ValidationError, match="Decryption failed"):
        d_decrypt(bound, "pw")
    with pytest.raises(ValidationError, match="Decryption failed"):
        d_decrypt(base, "pw", context=b"users.email")


@needs_crypto
@pytest.mark.parametrize("bad", ["empty", "short", "tampered", "encrypt"])
def test_d_decrypt_rejects_invalid_data(bad: str) -> None:
    blobs = {
        "empty": b"",
        "short": b"abc",
        "tampered": _flip(d_encrypt(b"abc", "pw"), 0),
        "encrypt": encrypt(b"abc", "pw"),
    }
    with pytest.raises(ValidationError, match="Decryption failed") as exc_info:
        d_decrypt(blobs[bad], "pw")
    assert isinstance(exc_info.value.__cause__, _invalid_tag())


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


def _explode(_: bytes) -> None:
    """Fail the way a broken `data_resolver` would."""
    raise ZeroDivisionError


@needs_crypto
def test_resolver_errors_propagate_unwrapped() -> None:
    with pytest.raises(ZeroDivisionError):
        decrypt(encrypt(b"x", "pw"), "pw", data_resolver=_explode)
    with pytest.raises(ZeroDivisionError):
        d_decrypt(d_encrypt(b"x", "pw"), "pw", data_resolver=_explode)
