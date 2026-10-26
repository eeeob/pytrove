from __future__ import annotations as _annotations

from importlib.util import find_spec

import pytest

from pytrove.crypto_tools import _internal

_HAS_CRYPTO = find_spec("cryptography") is not None
needs_crypto = pytest.mark.skipif(not _HAS_CRYPTO, reason="needs the `crypto` extra")


def test_layout_constants() -> None:
    assert (_internal._SALT_LEN, _internal._NONCE_LEN, _internal._TAG_LEN) == (16, 12, 16)
    assert _internal._ITERATIONS == 200_000


@needs_crypto
def test_derive_key_known_answer() -> None:
    # Pinned output: changing it breaks decryption of every stored `encrypt` ciphertext.
    assert _internal._derive_key("pw", b"s" * 16).hex() == (
        "7f73f48744cd0ea1ba72894af16a2ae7819419ccb7eb86978aa81d36dac17d63"
    )


@needs_crypto
def test_deterministic_key_known_answer() -> None:
    # Pinned output: changing it breaks decryption of every stored `d_encrypt` ciphertext.
    assert _internal._derive_deterministic_key("pw").hex() == (
        "a5a64050a9e90767c149a802fbf8ed8e23053073355f6f902f6b145453ffbdbf"
        "808f5703f925bd6844cfe7658bb786594c64514889ed71100d3069e554287b01"
    )


@needs_crypto
def test_derive_key_depends_on_password_and_salt() -> None:
    key = _internal._derive_key("pw", b"s" * 16)
    assert len(key) == 32
    assert key == _internal._derive_key("pw", bytearray(b"s" * 16))
    assert key != _internal._derive_key("pw", b"t" * 16)
    assert key != _internal._derive_key("other", b"s" * 16)


@needs_crypto
def test_deterministic_key_depends_on_the_password_and_context() -> None:
    key = _internal._derive_deterministic_key("pw")
    assert len(key) == 64
    assert key == _internal._derive_deterministic_key("pw", b"")
    assert key != _internal._derive_deterministic_key("other")
    assert key != _internal._derive_deterministic_key("pw", b"ctx")
    assert _internal._derive_deterministic_key("pw", b"a") != _internal._derive_deterministic_key(
        "pw", b"b"
    )


@pytest.mark.skipif(_HAS_CRYPTO, reason="needs the `crypto` extra to be missing")
def test_key_derivation_needs_the_crypto_extra() -> None:
    for derive in (
        lambda: _internal._derive_key("pw", b"s" * 16),
        lambda: _internal._derive_deterministic_key("pw"),
    ):
        with pytest.raises(ImportError, match="crypto"):
            derive()
