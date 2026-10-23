"""Password-based encryption: random (AES-GCM) and deterministic (AES-SIV)."""

from __future__ import annotations as _annotations

import os
from typing import TYPE_CHECKING, Any, overload

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM, AESSIV
except ImportError:
    pass

from .._internal import _optional_import
from ..errors import ValidationError
from ._internal import _derive_deterministic_key, _derive_key, _NONCE_LEN, _SALT_LEN, _TAG_LEN

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..typings import _T


@_optional_import(("cryptography", "crypto"))
def encrypt(data: bytes | str, password: str) -> bytes:
    """Encrypt with AES-GCM under a fresh random salt and nonce.

    The same input encrypts differently every time, so ciphertexts reveal
    nothing about equal plaintexts; use `d_encrypt` only when equality must
    stay checkable.

    Args:
        data: The plaintext; text is UTF-8 encoded.
        password: The password.

    Returns:
        `salt + nonce + ciphertext`, as `decrypt` expects.
    """
    if isinstance(data, str):
        data = data.encode()

    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    return salt + nonce + AESGCM(_derive_key(password, salt)).encrypt(nonce, data, None)


@overload
def decrypt(encrypted_data: bytes, password: str, data_resolver: None = None) -> bytes: ...
@overload
def decrypt(encrypted_data: bytes, password: str, data_resolver: Callable[[bytes], _T]) -> _T: ...
@_optional_import(("cryptography", "crypto"))
def decrypt(
    encrypted_data: bytes, password: str, data_resolver: Callable[[bytes], Any] | None = None
) -> Any:
    """Decrypt what `encrypt` produced.

    Args:
        encrypted_data: `salt + nonce + ciphertext`.
        password: The password.
        data_resolver: Converts the plaintext bytes, such as `bytes.decode`.

    Returns:
        The plaintext, converted when `data_resolver` is given.

    Raises:
        ValidationError: If the data is too short, the password is wrong or the data was altered.
    """
    if len(encrypted_data) < _SALT_LEN + _NONCE_LEN + _TAG_LEN:
        msg = "Data length is too short"
        raise ValidationError(msg)

    salt = encrypted_data[:_SALT_LEN]
    nonce = encrypted_data[_SALT_LEN : _SALT_LEN + _NONCE_LEN]
    ciphertext = encrypted_data[_SALT_LEN + _NONCE_LEN :]

    try:
        data_bytes = AESGCM(_derive_key(password, salt)).decrypt(nonce, ciphertext, None)
    except Exception as e:
        msg = "Decryption failed. Wrong password or corrupted data."
        raise ValidationError(msg) from e

    return data_bytes if data_resolver is None else data_resolver(data_bytes)


@_optional_import(("cryptography", "crypto"))
def d_encrypt(data: bytes | str, password: str) -> bytes:
    """Encrypt deterministically with AES-SIV: the same input always gives the same output.

    That lets equal plaintexts be matched (as a lookup key, say) and also
    reveals that they are equal; use `encrypt` for everything else.

    Args:
        data: The plaintext; text is UTF-8 encoded.
        password: The password.

    Returns:
        The ciphertext.
    """
    if isinstance(data, str):
        data = data.encode()

    return AESSIV(_derive_deterministic_key(password)).encrypt(data, [])


@overload
def d_decrypt(encrypted_data: bytes, password: str, data_resolver: None = None) -> bytes: ...
@overload
def d_decrypt(encrypted_data: bytes, password: str, data_resolver: Callable[[bytes], _T]) -> _T: ...
@_optional_import(("cryptography", "crypto"))
def d_decrypt(
    encrypted_data: bytes, password: str, data_resolver: Callable[[bytes], Any] | None = None
) -> Any:
    """Decrypt what `d_encrypt` produced.

    Args:
        encrypted_data: The ciphertext.
        password: The password.
        data_resolver: Converts the plaintext bytes.

    Returns:
        The plaintext, converted when `data_resolver` is given.

    Raises:
        ValidationError: If the password is wrong or the data was altered.
    """
    try:
        decrypted_data = AESSIV(_derive_deterministic_key(password)).decrypt(encrypted_data, [])
    except Exception as e:
        msg = "Decryption failed. Check your password or data integrity."
        raise ValidationError(msg) from e

    return decrypted_data if data_resolver is None else data_resolver(decrypted_data)


__all__ = (
    "encrypt",
    "decrypt",
    "d_encrypt",
    "d_decrypt",
)
