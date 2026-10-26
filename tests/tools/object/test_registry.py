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


def test_weak_registry_accepts_a_key_again_once_its_owner_is_collected() -> None:
    class Strict(WeakRegistry[str], allow_duplicate_keys=False):
        """Refuses live duplicates."""

    first = Strict("k")
    assert Strict.__instances__["k"] is first
    del first
    gc.collect()

    second = Strict("k")
    assert Strict.__instances__["k"] is second


def test_weak_registry_lets_an_instance_re_register_its_own_key() -> None:
    class Strict(WeakRegistry[str], allow_duplicate_keys=False):
        """Refuses live duplicates, but not the same instance."""

    obj = Strict("k")
    obj.__init__("k")
    assert Strict.__instances__["k"] is obj


def test_weak_registry_uses_the_id_for_an_explicit_none_key() -> None:
    class Loose(WeakRegistry[str], allow_duplicate_keys=False):
        """Keys by id when given `None`."""

    a = Loose(None)
    b = Loose(None)
    assert Loose.__instances__[id(a)] is a
    assert Loose.__instances__[id(b)] is b


def test_weak_registry_passes_other_class_keywords_on() -> None:
    seen: list[dict[str, object]] = []

    class Hooked(WeakRegistry[str]):
        """Records the keywords its subclasses receive."""

        def __init_subclass__(cls, **kwargs: object) -> None:
            """Record, then hand on to `WeakRegistry`."""
            seen.append(dict(kwargs))
            super().__init_subclass__(**kwargs)

    class Child(Hooked, allow_duplicate_keys=False):
        """Passes the keyword through `Hooked`."""

    assert seen == [{"allow_duplicate_keys": False}]
    assert Child.__allow_duplicate_keys__ is False

    with pytest.raises(TypeError):

        class Bad(WeakRegistry[str], unknown=True):  # ty: ignore[unknown-argument]  # The error under test.
            """`object.__init_subclass__` refuses the stray keyword."""


def test_weak_registry_keeps_separate_id_tables_per_subclass() -> None:
    class One(WeakRegistry):
        """Keyed by id."""

    class Two(WeakRegistry):
        """Keyed by id."""

    one = One()
    two = Two()
    assert One.__instances__ is not Two.__instances__
    assert id(one) not in Two.__instances__
    assert id(two) not in One.__instances__
