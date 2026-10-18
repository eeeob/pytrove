from __future__ import annotations as _annotations

import pytest

from pytrove.data_tools import KeyDefaultWeakKeyDict
from pytrove.object_tools import FrozenClassAttrs, classproperty, hybridmethod


def test_classproperty_reads_on_the_class_and_caches_per_class() -> None:
    calls: list[type] = []

    class Base:
        """Uses both kinds."""

        @classproperty
        def name(cls) -> str:
            """The class name."""
            return cls.__name__

        @classproperty(cached=True)
        def heavy(cls) -> list[type]:
            """Computed once per class."""
            calls.append(cls)
            return [cls]

    class Child(Base):
        """A subclass with its own cache."""

    assert Base.name == "Base"
    assert Child().name == "Child"
    assert Base.heavy is Base.heavy
    assert Child.heavy == [Child]
    assert calls == [Base, Child]
    assert Base.__dict__["name"].__doc__ == "The class name."


def test_classproperty_takes_an_explicit_doc_and_a_cache_table() -> None:
    plain = classproperty(lambda cls: 1, doc="given")
    cached = classproperty(lambda cls: 1, cached=True)
    assert plain.__doc__ == "given"
    assert not isinstance(plain.call, KeyDefaultWeakKeyDict)
    assert isinstance(cached.call, KeyDefaultWeakKeyDict)


def test_classproperty_returns_itself_without_an_owner() -> None:
    prop = classproperty(lambda cls: 1)
    assert prop.__get__(None, None) is prop


def test_classproperty_does_not_cache_a_getter_that_returns_the_property() -> None:
    prop: classproperty[object, object] = classproperty(lambda cls: prop, cached=True)

    class Owner:
        """Looked up on."""

    assert prop.__get__(None, Owner) is prop
    assert Owner not in prop.call


def test_hybridmethod_receives_class_or_instance() -> None:
    class Thing:
        """Has a hybrid method."""

        @hybridmethod
        def who(self_or_cls: object) -> object:
            """Return what it was bound to."""
            return self_or_cls

    thing = Thing()
    assert Thing.who() is Thing
    assert thing.who() is thing


def test_frozen_class_attrs() -> None:
    class Config(FrozenClassAttrs):
        """A class attribute instances cannot shadow."""

        limit = 3

    config = Config()
    config.other = 1

    with pytest.raises(AttributeError, match="limit"):
        config.limit = 4
