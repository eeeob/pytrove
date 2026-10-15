from __future__ import annotations as _annotations

import gc
import logging
import time

import pytest

from pytrove.data_tools import (
    DefaultWeakKeyDict,
    DefaultWeakValueDict,
    KeyDefaultDict,
    KeyDefaultWeakKeyDict,
    KeyDefaultWeakValueDict,
)
from pytrove.data_tools._factories import _no_arg_factory
from pytrove.logging_tools import UTC3LogFormatter
from pytrove.object_tools import (
    FrozenClassAttrs,
    RestrictedProxy,
    WeakRegistry,
    WeakRestrictedProxy,
    classproperty,
    hybridmethod,
)
from pytrove.object_tools._internal import _WeakRegistryKT


class _Box:
    """A weak-referenceable value."""

    def __init__(self, n: int = 0) -> None:
        """Store `n`."""
        self.n = n


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
    assert _WeakRegistryKT.__bound__ is not None


def test_restricted_proxies() -> None:
    box = _Box(3)
    blocked = RestrictedProxy(box, blocked="n")
    allowed = RestrictedProxy(box, allowed=["n"])
    assert allowed.n == 3

    with pytest.raises(AttributeError, match="blocked"):
        _ = blocked.n

    with pytest.raises(AttributeError, match="not allowed"):
        allowed.other = 1

    with pytest.raises(ValueError):
        RestrictedProxy(box, blocked="a", allowed="b")

    target = _Box(4)
    weak = WeakRestrictedProxy(target, blocked="secret")
    assert weak.n == 4
    del target
    gc.collect()

    with pytest.raises(ReferenceError):
        _ = weak.n


def test_key_default_dicts_build_missing_values() -> None:
    plain = KeyDefaultDict(str.upper)
    assert plain["a"] == "A"
    assert plain("b") == "B"

    keyed_values = KeyDefaultWeakValueDict(lambda k: _Box(k))
    assert keyed_values(2).n == 2

    values = DefaultWeakValueDict(_Box)
    held = values["x"]
    assert values["x"] is held

    key = _Box()
    assert KeyDefaultWeakKeyDict(lambda k: k.n)[key] == 0
    assert DefaultWeakKeyDict(list)(key) == []

    for factory in (KeyDefaultWeakValueDict, KeyDefaultWeakKeyDict):
        with pytest.raises(TypeError):
            factory(5)


def test_no_arg_factory_unwraps_its_own_adapter() -> None:
    adapter = _no_arg_factory(list)
    assert adapter("ignored") == []
    assert _no_arg_factory(adapter)("ignored") == []

    with pytest.raises(TypeError):
        _no_arg_factory(5)


def test_utc3_formatter_writes_utc_plus_3() -> None:
    record = logging.LogRecord("x", logging.INFO, "f", 1, "m", None, None)
    record.created = 0.0
    assert UTC3LogFormatter("%(asctime)s").format(record).startswith("1970-01-01 03:00:00")
    assert isinstance(UTC3LogFormatter().converter(0.0), time.struct_time)
