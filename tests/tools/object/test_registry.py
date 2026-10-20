from __future__ import annotations as _annotations

import gc

import pytest

from pytrove.object_tools import WeakRegistry


def test_weak_registry_tracks_live_instances_per_class() -> None:
    class Widget(WeakRegistry[str], allow_duplicate_keys=False):
        """Refuses duplicate keys."""

    class Loose(WeakRegistry):
        """Uses the id."""

    first = Widget("a")
    assert Widget.__instances__["a"] is first

    with pytest.raises(ValueError, match="already registered"):
        Widget("a")

    loose = Loose()
    assert Loose.__instances__[id(loose)] is loose
    assert "a" not in Loose.__instances__
    del first
    gc.collect()
    assert "a" not in Widget.__instances__


def test_weak_registry_replaces_a_live_key_by_default() -> None:
    class Open(WeakRegistry[str]):
        """Allows duplicate keys."""

    first = Open("k")
    second = Open("k")
    assert Open.__instances__["k"] is second
    assert first is not second


def test_weak_registry_inherits_the_duplicate_policy_when_not_given() -> None:
    class Strict(WeakRegistry[str], allow_duplicate_keys=False):
        """Refuses duplicates."""

    class Child(Strict):
        """Says nothing, so it inherits."""

    assert Child.__allow_duplicate_keys__ is False
    assert Child.__instances__ is not Strict.__instances__
    kept = Child("x")
    assert Child.__instances__["x"] is kept

    with pytest.raises(ValueError, match="duplicate keys"):
        Child("x")
