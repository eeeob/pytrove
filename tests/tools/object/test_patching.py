from __future__ import annotations as _annotations

import functools
from typing import Any

import pytest

from pytrove.object_tools import patch_cls, patch_into, unwrap, unwrap_cls, walk_subclasses


def _decorate(func: Any) -> Any:
    """Wrap `func` with `functools.wraps`."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Call `func`."""
        return func(*args, **kwargs)

    return wrapper


def test_unwrap_cls_replaces_wrapped_methods() -> None:
    class Thing:
        """A class with one wrapped method."""

        @_decorate
        def method(self) -> int:
            """Return one."""
            return 1

    raw = Thing.__dict__["method"].__wrapped__
    assert unwrap_cls(Thing) == 1
    assert Thing.method is raw


def test_unwrap_peels_properties_partialmethods_and_wrappers() -> None:
    def base(self: Any, x: int = 0) -> int:
        """Return `x`."""
        return x

    assert unwrap(property(_decorate(base))) is base
    assert unwrap(functools.partialmethod(base, 1)) is base
    prop = property(base)
    assert unwrap(prop, with_prop=False) is prop


def test_patch_into_copies_only_marked_members() -> None:
    class Target:
        """The class being patched."""

        def kept(self) -> str:
            """Return the original."""
            return "old"

    @patch_into(Target)
    class Patches:
        """Holds the patches."""

        def kept(self) -> str:
            """Return the patch."""
            return "new"

        kept.should_patch = True

        def added(self) -> str:
            """Not on the target yet."""
            return "added"

        added.should_patch = True

        def ignored(self) -> None:
            """Not marked."""

    assert Target().kept() == "new"
    assert Target().oldkept() == "old"
    assert Target().added() == "added"
    assert not hasattr(Target, "oldadded")
    assert not hasattr(Target, "ignored")
    assert Patches.__name__ == "Patches"


def test_patch_into_honours_the_key_the_setter_and_preserve_old() -> None:
    sets: list[str] = []

    class Target:
        """The class being patched."""

        def kept(self) -> str:
            """Return the original."""
            return "old"

    def setter(target: type, name: str, value: Any) -> None:
        """Record and set."""
        sets.append(name)
        setattr(target, name, value)

    @patch_into(Target, patch_key="apply", preserve_old=False, setter=setter)
    class Patches:
        """Holds the patches."""

        def kept(self) -> str:
            """Return the patch."""
            return "new"

        kept.apply = True

        def other(self) -> None:
            """Marked with the default key only."""

        other.should_patch = True

    assert sets == ["kept"]
    assert Target().kept() == "new"
    assert not hasattr(Target, "oldkept")


def test_patch_cls_merges_methods_into_base() -> None:
    class Base:
        """The class being patched."""

        def greet(self) -> str:
            """Return the original."""
            return "base"

    class Patch(Base):
        """Holds the patches."""

        def greet(self) -> str:
            """Return the patch."""
            return "patched"

    assert patch_cls(Patch) is Base
    assert Base().greet() == "patched"
    assert Base().oldgreet() == "base"


def test_patch_cls_copies_the_body_and_skips_unlisted_dunders() -> None:
    class Base:
        """The class being patched."""

        def __repr__(self) -> str:
            """Original repr."""
            return "base"

    @patch_cls(preserve_old=False)
    class Patch(Base):
        """Holds the patches."""

        def __repr__(self) -> str:
            """Patched repr."""
            return "patched"

        def extra(self) -> int:
            """A new method."""
            return 2

    assert Patch is Base
    assert Base().extra() == 2
    assert repr(Base()) == "base"
    assert not hasattr(Base, "oldextra")


def test_patch_cls_copies_the_listed_dunders() -> None:
    class Base:
        """The class being patched."""

        def __init__(self) -> None:
            """Original init."""
            self.v = 1

    @patch_cls(include_dunders=("__init__", "__repr__"))
    class Patch(Base):
        """Holds the patches."""

        def __init__(self) -> None:
            """Patched init."""
            self.v = 2

        def __repr__(self) -> str:
            """Patched repr."""
            return "patched"

    assert Base().v == 2
    assert repr(Base()) == "patched"
    assert Base.old__init__ is not Base.__init__


def test_patch_cls_requires_single_base() -> None:
    class First: ...
    class Second: ...

    with pytest.raises(TypeError, match="exactly one base"):

        @patch_cls
        class BadPatch(First, Second):
            """Two bases."""

    with pytest.raises(TypeError, match="exactly one base"):

        @patch_cls
        class NoBase:
            """No base but `object`."""


def test_walk_subclasses_yields_a_diamond_once() -> None:
    class Base: ...
    class Left(Base): ...
    class Right(Base): ...
    class Bottom(Left, Right): ...

    names = [c.__name__ for c in walk_subclasses(Base)]

    assert sorted(names) == ["Bottom", "Left", "Right"]


def test_walk_subclasses_can_start_with_the_base() -> None:
    class Base: ...
    class Child(Base): ...

    assert list(walk_subclasses(Base, include_base=True)) == [Base, Child]
    assert list(walk_subclasses(Child)) == []
