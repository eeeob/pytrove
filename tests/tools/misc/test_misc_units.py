from __future__ import annotations as _annotations

import functools
from typing import Any

import pytest

from pytrove.misc_tools import generate_secret, patch_cls, patch_into, unwrap, unwrap_cls


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

        def ignored(self) -> None:
            """Not marked."""

    assert Target().kept() == "new"
    assert Target().oldkept() == "old"
    assert not hasattr(Target, "ignored")
    assert Patches.__name__ == "Patches"


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


def test_generate_secret_requires_room_for_each_set() -> None:
    with pytest.raises(ValueError, match="too small"):
        generate_secret(2)

    assert len(generate_secret(4)) == 4
