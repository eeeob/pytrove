from __future__ import annotations as _annotations

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
