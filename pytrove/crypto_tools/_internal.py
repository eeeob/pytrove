"""Helpers private to `crypto_tools`: key derivation and the ciphertext layout."""

from __future__ import annotations as _annotations

from typing import Final

try:
    from cryptography.hazmat.primitives import hashes  # type: ignore[import-not-found]  # Optional: the `crypto` extra.
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # type: ignore[import-not-found]  # Optional: the `crypto` extra.
except ImportError:
    pass

from .._internal import _optional_import

_ITERATIONS: Final[int] = 200_000
"""PBKDF2-SHA256 rounds for every derived key."""

_SALT_LEN: Final[int] = 16
"""Bytes of random salt prepended by `encrypt`."""

_NONCE_LEN: Final[int] = 12
"""Bytes of AES-GCM nonce following the salt."""

_TAG_LEN: Final[int] = 16
"""Bytes of AES-GCM authentication tag; with salt and nonce, the shortest valid ciphertext is 44."""


def _pbkdf2(secret: bytes, salt: bytes, length: int) -> bytes:
    """Run PBKDF2-HMAC-SHA256 for `_ITERATIONS` rounds.

    Args:
        secret: The password bytes.
        salt: The salt.
        length: Key bytes to derive.

    Returns:
        `length` key bytes.
    """
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=length, salt=salt, iterations=_ITERATIONS)
    return kdf.derive(secret)


@_optional_import("crypto")
def _derive_key(master_key: str, salt: bytes | bytearray | memoryview) -> bytes:
    """Derive a 256-bit AES-GCM key from a password and a random salt.

    Args:
        master_key: The password.
        salt: The salt stored with the ciphertext.

    Returns:
        32 key bytes.
    """
    return _pbkdf2(master_key.encode(), bytes(salt), 32)  # `cryptography` takes `bytes` only.


@_optional_import("crypto")
def _derive_deterministic_key(password: str, context: bytes = b"") -> bytes:
    """Derive an AES-SIV key from a password, salted with the hash of `context + password`.

    The same password and context always yield the same key, which is what makes
    `d_encrypt` deterministic; an empty `context` keeps the original password-only salt.

    Args:
        password: The password.
        context: Application-specific bytes that separate keys sharing a password.

    Returns:
        64 key bytes.
    """
    secret = password.encode()
    digest = hashes.Hash(hashes.SHA256())
    digest.update(context + secret)
    return _pbkdf2(secret, digest.finalize()[:16], 64)


__all__ = (
    "_derive_deterministic_key",
    "_derive_key",
    "_ITERATIONS",
    "_NONCE_LEN",
    "_SALT_LEN",
    "_TAG_LEN",
)
