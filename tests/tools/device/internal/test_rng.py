from __future__ import annotations as _annotations

import pytest

from pytrove.device_tools._internal.rng import _rng


def test_rng_is_reproducible_per_seed() -> None:
    assert _rng("a").random() == _rng("a").random()
    assert _rng("a").random() != _rng("b").random()


def test_rng_seeds_non_text_by_its_str() -> None:
    assert _rng(5).random() == _rng("5").random()


def test_rng_seeds_bytes_and_text_alike() -> None:
    assert _rng(b"a").random() == _rng("a").random()
    assert _rng(bytearray(b"a")).random() == _rng("a").random()


def test_rng_without_a_seed_differs_each_time() -> None:
    assert _rng().random() != _rng().random()


# Golden values: a change here reassigns every stored account's device, so it is never silent.
@pytest.mark.parametrize(
    ("seed", "first"),
    [
        ("acc-1", 0.15674838796725232),
        ("", 0.6048192170315362),
        ("é", 0.9930333590967806),
        (b"\xff", 0.4740796386055668),
        (42, 0.9355934424485339),
    ],
)
def test_rng_seed_derivation_is_pinned(seed: object, first: float) -> None:
    assert _rng(seed).random() == first


def test_rng_encodes_text_as_utf8() -> None:
    assert _rng("é").random() == _rng("é".encode()).random()
