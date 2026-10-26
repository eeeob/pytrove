from __future__ import annotations as _annotations

import gc

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


def test_classproperty_takes_options_in_the_decorator_form() -> None:
    class Owner:
        """Uses the options form."""

        @classproperty(doc="given")
        def plain(cls) -> str:
            """Ignored: `doc` wins."""
            return cls.__name__

    prop = Owner.__dict__["plain"]
    assert prop.__doc__ == "given"
    assert not isinstance(prop.call, KeyDefaultWeakKeyDict)
    assert Owner.plain == "Owner"


def test_classproperty_does_not_cache_a_getter_that_raises() -> None:
    calls: list[type] = []

    class Owner:
        """Fails once, then works."""

        @classproperty(cached=True)
        def flaky(cls) -> int:
            """Raise on the first call."""
            calls.append(cls)

            if len(calls) == 1:
                msg = "first call"
                raise RuntimeError(msg)

            return len(calls)

    with pytest.raises(RuntimeError, match="first call"):
        _ = Owner.flaky

    assert Owner.flaky == 2
    assert Owner.flaky == 2
    assert Owner().flaky == 2
    assert calls == [Owner, Owner]


def test_classproperty_cache_releases_a_collected_class() -> None:
    prop: classproperty[object, int] = classproperty(lambda cls: 1, cached=True)

    class Owner:
        """Collected after the read."""

    assert prop.__get__(None, Owner) == 1
    assert len(prop.call) == 1
    del Owner
    gc.collect()
    assert len(prop.call) == 0


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

    class Sub(Thing):
        """Inherits it."""

    thing = Thing()
    sub = Sub()
    assert Thing.who() is Thing
    assert thing.who() is thing
    assert Sub.who() is Sub
    assert sub.who() is sub

    raw = Thing.__dict__["who"]
    assert raw.__func__ is raw.__wrapped__
    assert raw.__func__.__name__ == "who"


def test_frozen_class_attrs() -> None:
    class Config(FrozenClassAttrs):
        """A class attribute instances cannot shadow."""

        limit = 3

    config = Config()
    config.other = 1

    with pytest.raises(AttributeError, match="limit"):
        config.limit = 4

    Config.limit = 4
    assert config.limit == 4


def test_frozen_class_attrs_refuses_inherited_attributes_and_methods() -> None:
    class Base(FrozenClassAttrs):
        """Defines the names."""

        limit = 3

        def method(self) -> None:
            """A method."""

    class Child(Base):
        """Inherits them."""

    child = Child()

    with pytest.raises(AttributeError, match="limit"):
        child.limit = 4

    with pytest.raises(AttributeError, match="method"):
        child.method = None


def test_frozen_class_attrs_lets_data_descriptors_be_assigned() -> None:
    class WithSetter(FrozenClassAttrs):
        """A property with a setter."""

        def __init__(self) -> None:
            """Start at zero."""
            self._x = 0

        @property
        def x(self) -> int:
            """The value."""
            return self._x

        @x.setter
        def x(self, value: int) -> None:
            self._x = value

        @property
        def ro(self) -> int:
            """Read-only."""
            return 1

    class Slotted(FrozenClassAttrs):
        """A `__slots__` member."""

        __slots__ = ("a",)

    obj = WithSetter()
    obj.x = 5
    assert obj.x == 5

    with pytest.raises(AttributeError):
        obj.ro = 2

    slotted = Slotted()
    slotted.a = 5
    assert slotted.a == 5


def test_frozen_class_attrs_does_not_run_a_classproperty_getter() -> None:
    calls: list[type] = []

    class Config(FrozenClassAttrs):
        """A class property instances cannot shadow."""

        @classproperty
        def name(cls) -> str:
            """Record the call, then fail the way a missing attribute would."""
            calls.append(cls)
            msg = "not ready"
            raise AttributeError(msg)

    with pytest.raises(AttributeError, match="Cannot override class attribute 'name'"):
        Config().name = "other"

    assert calls == []
