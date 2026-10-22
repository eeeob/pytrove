from __future__ import annotations as _annotations

import inspect
from collections.abc import AsyncIterator

import pytest

from pytrove._internal._optional import (
    _build_error_msg,
    _get_missing,
    _is_installed,
    _optional_import,
    _parse_version,
    _split_spec,
    _unavailable_class,
    _version_ok,
)

MISSING = "no_such_package_for_pytrove"


def test_parse_version_keeps_the_numeric_release() -> None:
    assert _parse_version("2.2.24") == (2, 2, 24)
    assert _parse_version("1.16.0rc1") == (1, 16, 0)
    assert _parse_version("1.x.3") == (1, 3)


def test_split_spec_separates_name_and_clauses() -> None:
    assert _split_spec("kurigram>=2.2.24") == ("kurigram", ">=2.2.24")
    assert _split_spec(" wrapt >=1.16,<2") == ("wrapt", ">=1.16,<2")
    assert _split_spec("pytest") == ("pytest", "")
    assert _split_spec(">=1") == (">=1", "")


def test_version_ok_checks_every_clause() -> None:
    assert _version_ok("pytest", "")
    assert _version_ok("pytest", ">=1,!=0.1,<1000")
    assert not _version_ok("pytest", "<1")
    assert _version_ok(MISSING, ">=99")


def test_is_installed_uses_metadata_then_the_module() -> None:
    assert _is_installed("pytest")
    assert _is_installed("pytest>=1")
    assert not _is_installed("pytest<1")
    assert _is_installed("json")
    assert not _is_installed(MISSING)


def test_get_missing_and_the_error_message() -> None:
    packages = (("pytest", "dev"), ((MISSING, "json"), "nope"))
    missing = _get_missing(*packages)
    assert missing == [((MISSING,), "nope")]
    assert _get_missing(("pytest", "dev")) == []

    msg = _build_error_msg(packages, missing)
    assert "pip install 'pytrove[dev, nope]'" in msg
    assert f"Required : 'pytest', '{MISSING}', 'json'" in msg
    assert msg.endswith(f"Missing  : '{MISSING}'")


async def test_optional_import_passes_through_when_installed() -> None:
    @_optional_import(("pytest", "dev"))
    def sync(x: int) -> int:
        """Double `x`."""
        return x * 2

    @_optional_import(("pytest", "dev"))
    async def coro() -> int:
        """Return one."""
        return 1

    @_optional_import(("pytest", "dev"))
    async def agen() -> AsyncIterator[int]:
        """Yield two values."""
        yield 1
        yield 2

    assert sync(2) == 4 and sync.__doc__ == "Double `x`."
    assert inspect.iscoroutinefunction(coro) and await coro() == 1
    assert inspect.isasyncgenfunction(agen)
    assert [i async for i in agen()] == [1, 2]


async def test_optional_import_raises_only_on_call_when_missing() -> None:
    @_optional_import((MISSING, "nope"))
    def sync() -> int:
        """Return one."""
        return 1

    @_optional_import((MISSING, "nope"))
    async def coro() -> int:
        """Return one."""
        return 1

    @_optional_import((MISSING, "nope"))
    async def agen() -> AsyncIterator[int]:
        """Yield one value."""
        yield 1

    with pytest.raises(ImportError, match=r"pytrove\[nope\]"):
        sync()

    with pytest.raises(ImportError, match=r"pytrove\[nope\]"):
        await coro()

    with pytest.raises(ImportError, match=r"pytrove\[nope\]"):
        [i async for i in agen()]


def test_unavailable_class_refuses_every_use() -> None:
    stand_in = _unavailable_class("Thing", (MISSING, "nope"))
    assert stand_in.__name__ == "Thing"

    for use in (
        stand_in,
        lambda: stand_in.attr,
        lambda: stand_in[int],
        lambda: isinstance(1, stand_in),
        lambda: issubclass(int, stand_in),
        lambda: type("Sub", (stand_in,), {}),
    ):
        with pytest.raises(ImportError, match=r"pytrove\[nope\]"):
            use()


def test_unavailable_class_stays_inspectable() -> None:
    stand_in = _unavailable_class("Thing", (MISSING, "nope"))

    # A dunder probe gets `AttributeError`, so `inspect.unwrap` (and with it
    # `doctest` collection over a bare install) walks past the stand-in.
    assert getattr(stand_in, "__wrapped__", None) is None
    assert inspect.unwrap(stand_in) is stand_in

    with pytest.raises(ImportError, match=r"pytrove\[nope\]"):
        _ = stand_in.attr


def test_unavailable_class_refuses_instance_attribute_access() -> None:
    stand_in = _unavailable_class("Thing", (MISSING, "nope"))
    # `__new__` refuses, so build the instance past it to reach the instance `__getattr__`.
    instance = object.__new__(stand_in)

    with pytest.raises(ImportError, match=r"pytrove\[nope\]"):
        _ = instance.attr


def test_unavailable_class_requires_something_missing() -> None:
    with pytest.raises(RuntimeError, match="No missing packages"):
        _unavailable_class("Thing", ("pytest", "dev"))
