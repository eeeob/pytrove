"""Helpers private to `crypto_tools`: key derivation and the ciphertext layout."""

from __future__ import annotations as _annotations

from typing import Final

try:
    from cryptography.hazmat.backends import default_backend  # type: ignore[import-not-found]  # Optional: the `crypto` extra.
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


@_optional_import("crypto")
def _derive_key(master_key: str, salt: bytes) -> bytes:
    """Derive a 256-bit AES-GCM key from a password and a random salt.

    Args:
        master_key: The password.
        salt: The salt stored with the ciphertext.

    Returns:
        32 key bytes.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_ITERATIONS,
        backend=default_backend(),
    )
    return kdf.derive(master_key.encode())


@_optional_import("crypto")
def _derive_deterministic_key(password: str) -> bytes:
    """Derive an AES-SIV key from a password alone, salted with the password's own hash.

    The same password always yields the same key, which is what makes `d_encrypt` deterministic.

    Args:
        password: The password.

    Returns:
        64 key bytes.
    """
    digest = hashes.Hash(hashes.SHA256(), backend=default_backend())
    digest.update(password.encode())
    static_salt = digest.finalize()[:16]

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=64,
        salt=static_salt,
        iterations=_ITERATIONS,
        backend=default_backend(),
    )
    return kdf.derive(password.encode())


__all__ = (
    "_derive_deterministic_key",
    "_derive_key",
    "_ITERATIONS",
    "_NONCE_LEN",
    "_SALT_LEN",
    "_TAG_LEN",
)
