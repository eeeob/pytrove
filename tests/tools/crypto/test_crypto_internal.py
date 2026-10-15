from __future__ import annotations as _annotations

import pytest

pytest.importorskip("cryptography")

from pytrove.crypto_tools import _internal  # noqa: E402 - only importable once the skip above has passed.


def test_layout_constants() -> None:
    assert (_internal._SALT_LEN, _internal._NONCE_LEN, _internal._TAG_LEN) == (16, 12, 16)
    assert _internal._ITERATIONS == 200_000


def test_derive_key_depends_on_password_and_salt() -> None:
    key = _internal._derive_key("pw", b"s" * 16)
    assert len(key) == 32
    assert key == _internal._derive_key("pw", b"s" * 16)
    assert key != _internal._derive_key("pw", b"t" * 16)
    assert key != _internal._derive_key("other", b"s" * 16)


def test_deterministic_key_depends_on_the_password_alone() -> None:
    key = _internal._derive_deterministic_key("pw")
    assert len(key) == 64
    assert key == _internal._derive_deterministic_key("pw")
    assert key != _internal._derive_deterministic_key("other")
