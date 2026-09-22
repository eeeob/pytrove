from __future__ import annotations

from typing import Callable, overload

try:
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM, AESSIV
except ImportError:
    pass


from .typings import _T
from .errors import ValidationError

from ._optional import _optional_import

import os


@_optional_import(("cryptography", "crypto"))
def _derive_key(master_key: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200_000,
        backend=default_backend()
    )
    return kdf.derive(master_key.encode())

@_optional_import(("cryptography", "crypto"))
def _drive_deterministic_key(password: str) -> bytes:
    salt = hashes.Hash(hashes.SHA256(), backend=default_backend())
    salt.update(password.encode())
    static_salt = salt.finalize()[:16]

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=64,
        salt=static_salt,
        iterations=200_000,
        backend=default_backend()
    )
    return kdf.derive(password.encode())


@_optional_import(("cryptography", "crypto"))
def encrypt(data: bytes | str, password: str) -> bytes:
    """AES-GCM encryption with a random salt and nonce, prepended to the
    ciphertext so decrypt() can recover them without a separate channel.
    Encrypting the same `data`/`password` twice produces different output
    each time. See d_encrypt() below for the deterministic alternative and
    why picking the wrong one of the two is a real security mistake.
    """

    if isinstance(data, str):
        data = data.encode()

    salt = os.urandom(16)
    nonce = os.urandom(12)

    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    
    
    return salt + nonce + ciphertext
    

@overload
def decrypt(encrypted_data: bytes, password: str, data_resolver: None = None) -> bytes: ...
@overload
def decrypt(encrypted_data: bytes, password: str, data_resolver: Callable[[bytes], _T]) -> _T: ...
@_optional_import(("cryptography", "crypto"))
def decrypt(encrypted_data: bytes, password: str, data_resolver=None):
    # 16-byte salt + 12-byte nonce + 16-byte GCM tag is the minimum possible
    # length (for empty plaintext); anything shorter can never be valid.
    if len(encrypted_data) < 44:
        raise ValidationError("Data length is too short")

    salt = encrypted_data[:16]

    nonce_end = 16 + 12
    nonce = encrypted_data[16:nonce_end]

    ciphertext = encrypted_data[nonce_end:]

    aesgcm = AESGCM(_derive_key(password, salt))
    
    try:
        data_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as e:
        raise ValidationError("Decryption failed. Wrong password or corrupted data.") from e

    return data_bytes if data_resolver is None else data_resolver(data_bytes)

@_optional_import(("cryptography", "crypto"))
def d_encrypt(data: bytes | str, password: str) -> bytes:
    """AES-SIV deterministic encryption ("d_" = deterministic): the same
    `data`/`password` always produces the exact same ciphertext, because the
    key is derived from `password` alone (via _drive_deterministic_key(),
    with no random salt) and AES-SIV needs no nonce.

    Deliberate tradeoff, not a bug: determinism means an attacker who sees
    two ciphertexts can tell whether the underlying plaintexts are equal,
    which encrypt() above is specifically designed to prevent. Use this only
    when that equality needs to stay checkable (e.g. as a lookup key) and use
    encrypt() for everything else.
    """

    if isinstance(data, str):
        data = data.encode()
    
    aessiv = AESSIV(_drive_deterministic_key(password))

    return aessiv.encrypt(data, [])


@overload
def d_decrypt(encrypted_data: bytes, password: str, data_resolver: None = None) -> bytes: ...
@overload
def d_decrypt(encrypted_data: bytes, password: str, data_resolver: Callable[[bytes], _T]) -> _T: ...
@_optional_import(("cryptography", "crypto"))
def d_decrypt(encrypted_data: bytes, password: str, data_resolver=None):
    
    aessiv = AESSIV(_drive_deterministic_key(password))
    
    try:
        decrypted_data = aessiv.decrypt(encrypted_data, [])
    except Exception as e:
        raise ValidationError("Decryption failed. Check your password or data integrity.") from e
    
    return decrypted_data if data_resolver is None else data_resolver(decrypted_data)



__all__ = [
    "encrypt", 
    "decrypt", 
    "d_encrypt", 
    "d_decrypt"

]
