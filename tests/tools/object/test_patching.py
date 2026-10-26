from __future__ import annotations as _annotations

import abc
import functools
import inspect
from enum import EnumMeta
from typing import Any

import pytest

from pytrove.object_tools import (
    classproperty,
    patch_cls,
    patch_into,
    unwrap,
    unwrap_cls,
    walk_subclasses,
)


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


def test_unwrap_cls_keeps_classmethods_and_staticmethods_callable() -> None:
    class Thing:
        """Wrapped class and static methods."""

        @classmethod
        @_decorate
        def cm(cls) -> type:
            """Return the class."""
            return cls

        @staticmethod
        @_decorate
        def sm() -> int:
            """Return one."""
            return 1

    class Sub(Thing):
        """Binds `cm` to itself."""

    assert unwrap_cls(Thing) == 2
    assert isinstance(Thing.__dict__["cm"], classmethod)
    assert isinstance(Thing.__dict__["sm"], staticmethod)
    assert not hasattr(Thing.__dict__["cm"].__func__, "__wrapped__")
    assert not hasattr(Thing.__dict__["sm"].__func__, "__wrapped__")
    assert Thing.cm() is Thing
    assert Sub.cm() is Sub
    assert Thing().sm() == 1


def test_unwrap_cls_leaves_unwrapped_class_and_static_methods_alone() -> None:
    class Thing:
        """Plain class and static methods."""

        @classmethod
        def cm(cls) -> int:
            """Return one."""
            return 1

        @staticmethod
        def sm() -> int:
            """Return two."""
            return 2

    members = dict(vars(Thing))
    assert unwrap_cls(Thing) == 0
    assert Thing.__dict__["cm"] is members["cm"]
    assert Thing.__dict__["sm"] is members["sm"]


def test_unwrap_cls_unwraps_inherited_members_on_the_subclass_only() -> None:
    class Base:
        """Owns the wrapped method."""

        @_decorate
        def method(self) -> int:
            """Return one."""
            return 1

    class Child(Base):
        """Inherits it."""

    assert unwrap_cls(Child) == 1
    assert not hasattr(Child.__dict__["method"], "__wrapped__")
    assert Child().method() == 1
    assert hasattr(Base.__dict__["method"], "__wrapped__")


def test_unwrap_cls_does_not_run_descriptor_getters_or_touch_properties() -> None:
    calls: list[type] = []

    class Thing:
        """A class property, a property and a nested class carrying `__wrapped__`."""

        @classproperty
        def counted(cls) -> int:
            """Record the call."""
            calls.append(cls)
            return 1

        @property
        def prop(self) -> int:
            """Return one."""
            return 1

        class Nested:
            """A class-level `__wrapped__`."""

            __wrapped__ = staticmethod(_decorate(len))

    prop = Thing.__dict__["prop"]
    assert unwrap_cls(Thing) == 0
    assert calls == []
    assert Thing.__dict__["prop"] is prop
    assert isinstance(Thing.__dict__["Nested"], type)


def test_unwrap_peels_properties_partialmethods_and_wrappers() -> None:
    def base(self: Any, x: int = 0) -> int:
        """Return `x`."""
        return x

    assert unwrap(property(_decorate(base))) is base
    assert unwrap(functools.partialmethod(base, 1)) is base
    prop = property(base)
    assert unwrap(prop, unwrap_properties=False) is prop


def test_unwrap_peels_a_cached_property_unless_told_not_to() -> None:
    def base(self: Any) -> int:
        """Return one."""
        return 1

    cached = functools.cached_property(_decorate(base))

    assert unwrap(cached) is base
    assert unwrap(cached, unwrap_properties=False) is cached


@pytest.mark.parametrize("kind", [classmethod, staticmethod])
def test_unwrap_always_peels_classmethods_and_staticmethods(kind: Any) -> None:
    def base() -> int:
        """Return one."""
        return 1

    assert unwrap(kind(_decorate(base))) is base
    assert unwrap(kind(base), unwrap_properties=False) is base


def test_unwrap_takes_unwrap_properties_by_keyword_only() -> None:
    with pytest.raises(TypeError):
        unwrap(property(), False)


@pytest.mark.parametrize(
    "build",
    [
        lambda f: functools.partial(_decorate(f), None),
        lambda f: _decorate(functools.partial(f, None)),
        lambda f: property(functools.partial(_decorate(f), None)),
        lambda f: _decorate(property(f)),
        lambda f: _decorate(functools.partialmethod(f, 1)),
    ],
    ids=[
        "partial-of-wraps",
        "wraps-of-partial",
        "property-of-partial-of-wraps",
        "wraps-of-property",
        "wraps-of-partialmethod",
    ],
)
def test_unwrap_peels_layers_in_any_order(build: Any) -> None:
    def base(self: Any, x: int = 0) -> int:
        """Return `x`."""
        return x

    assert unwrap(build(base)) is base


def test_unwrap_returns_none_for_a_property_without_a_getter() -> None:
    assert unwrap(property()) is None


def test_unwrap_returns_a_class_unpeeled() -> None:
    class Proxyish:
        """Carries `__wrapped__` as a class-level property."""

        @property
        def __wrapped__(self) -> int:
            """The wrapped value."""
            return 1

    assert unwrap(Proxyish) is Proxyish


def test_unwrap_raises_on_a_wrapper_loop() -> None:
    def func() -> None:
        """Wrap a partial of itself."""

    func.__wrapped__ = functools.partial(func)

    with pytest.raises(ValueError, match="wrapper loop when unwrapping"):
        unwrap(func)


def test_patch_into_reads_the_marker_on_any_layer() -> None:
    class Target:
        """The class being patched."""

    def base(self: Any) -> str:
        """Return the patch."""
        return "new"

    def inner(self: Any) -> str:
        """Return the inner patch."""
        return "inner"

    marked_partial = functools.partial(base)
    marked_partial.should_patch = True
    marked_wrapper = _decorate(base)
    marked_wrapper.should_patch = True
    marked_inner = _decorate(inner)
    marked_inner.should_patch = True

    @patch_into(Target)
    class Patches:
        """Holds the patches."""

        by_partial = marked_partial
        by_wrapper = marked_wrapper
        by_inner = functools.partialmethod(_decorate(marked_inner))
        unmarked = functools.partial(_decorate(base))

    assert Target.__dict__["by_partial"] is marked_partial
    assert Target.__dict__["by_wrapper"] is marked_wrapper
    assert Target().by_inner() == "inner"
    assert not hasattr(Target, "unmarked")


@pytest.mark.parametrize("kind", [property, functools.cached_property])
def test_patch_into_reads_the_marker_under_a_getter_only_with_unwrap_properties(
    kind: Any,
) -> None:
    def getter(self: Any) -> str:
        """Return the patch."""
        return "new"

    getter.should_patch = True

    class Target:
        """The class being patched."""

    @patch_into(Target, unwrap_properties=False)
    class Skipped:
        """Holds the patch, marked only under its getter."""

        value = kind(getter)

    assert not hasattr(Target, "value")

    @patch_into(Target)
    class Patches:
        """Holds the patch, marked only under its getter."""

        value = kind(getter)

    assert Target.__dict__["value"] is Patches.__dict__["value"]
    assert Target().value == "new"


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


def test_patch_into_preserves_the_raw_old_member() -> None:
    class Target:
        """Static and class members."""

        @staticmethod
        def s() -> str:
            """Return the original."""
            return "old-s"

        @classmethod
        def c(cls) -> type:
            """Return the class it is bound to."""
            return cls

    class Sub(Target):
        """Binds `oldc` to itself."""

    def new(*_: Any) -> str:
        """The patch."""
        return "new"

    new.should_patch = True

    @patch_into(Target)
    class Patches:
        """Holds the patches."""

        s = staticmethod(new)
        c = classmethod(new)

    assert isinstance(Target.__dict__["olds"], staticmethod)
    assert Target().olds() == "old-s"
    assert Sub.oldc() is Sub


def test_patch_into_propagates_a_wrapper_loop() -> None:
    class Target:
        """The class being patched."""

    def func() -> None:
        """Wrap a partial of itself."""

    func.__wrapped__ = functools.partial(func)

    with pytest.raises(ValueError, match="wrapper loop when unwrapping"):

        @patch_into(Target)
        class Patches:
            """Holds the looping member."""

            looping = func


def test_patch_cls_preserves_the_raw_old_member() -> None:
    calls: list[type] = []

    class Base:
        """A static method and a class property."""

        @staticmethod
        def s() -> str:
            """Return the original."""
            return "old"

        @classproperty
        def p(cls) -> str:
            """Record the call."""
            calls.append(cls)
            return "old-p"

    @patch_cls
    class Patch(Base):
        """Holds the patches."""

        @staticmethod
        def s() -> str:
            """Return the patch."""
            return "new"

        @classproperty
        def p(cls) -> str:
            """Return the patch."""
            return "new-p"

    assert calls == []
    assert Patch is Base
    assert isinstance(Base.__dict__["olds"], staticmethod)
    assert Base().s() == "new"
    assert Base().olds() == "old"
    assert isinstance(Base.__dict__["oldp"], classproperty)
    assert Base.oldp == "old-p"
    assert Base.p == "new-p"


def test_patch_cls_breaks_zero_argument_super_as_documented() -> None:
    class Root:
        """The class being patched."""

        def __init__(self) -> None:
            """Original init."""
            self.v = 1

    @patch_cls
    class Patch(Root):
        """Uses `super()`, which still names `Patch` after the copy."""

        def __init__(self) -> None:
            """Patched init."""
            super().__init__()

    with pytest.raises(TypeError, match="super"):
        Root()


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


def test_walk_subclasses_yields_the_base_once_in_a_diamond() -> None:
    class Base: ...

    class Left(Base): ...

    class Right(Base): ...

    class Bottom(Left, Right): ...

    walked = list(walk_subclasses(Base, include_base=True))

    assert walked[0] is Base
    assert sorted(c.__name__ for c in walked) == ["Base", "Bottom", "Left", "Right"]


@pytest.mark.parametrize("meta", [type, abc.ABCMeta, EnumMeta])
def test_walk_subclasses_works_on_a_metaclass(meta: type) -> None:
    class Custom(meta): ...  # ty: ignore[unsupported-base]  # A parametrised metaclass base.

    assert Custom in set(walk_subclasses(meta))


def test_walk_subclasses_is_lazy() -> None:
    class Base: ...

    class Child(Base): ...

    walked = walk_subclasses(Base)

    assert inspect.isgenerator(walked)
    assert next(walked) is Child
