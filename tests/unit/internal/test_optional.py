from __future__ import annotations as _annotations

import inspect
from importlib.metadata import PackageNotFoundError
from typing import TYPE_CHECKING

import pytest

from pytrove._internal import _optional
from pytrove._internal._optional import (
    _build_error_msg,
    _has_requirement,
    _optional_import,
    _requirements,
    _unavailable_class,
    _unmet,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

_REQUIRES = [
    "typing-extensions>=4.4; python_version < '3.13'",
    "okpkg>=1.0; extra == 'good'",
    "oldpkg>=2.0,<3; extra == 'old'",
    "prepkg>=1.0; extra == 'pre'",
    "nopkg>=1.0; extra == 'gone'",
    "farpkg>=1.0; (python_version < '3.0') and extra == 'far'",
    "okpkg>=1.0; (python_version < '3.0') and extra == 'farok'",
]
_INSTALLED = {"okpkg": "1.2", "oldpkg": "1.9", "prepkg": "1.1rc1"}


def _fake_version(name: str) -> str:
    """Report the fake installed version of `name`."""
    try:
        return _INSTALLED[name]
    except KeyError:
        raise PackageNotFoundError(name) from None


@pytest.fixture(autouse=True)
def fake_metadata(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Serve pytrove's requirements and the installed versions from the tables above."""
    monkeypatch.setattr(_optional, "requires", lambda _: _REQUIRES)
    monkeypatch.setattr(_optional, "version", _fake_version)
    _requirements.cache_clear()
    yield
    _requirements.cache_clear()


def _no_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make pytrove's own metadata missing, as on a source tree."""

    def missing(_: str) -> list[str]:
        name = "pytrove"
        raise PackageNotFoundError(name)

    monkeypatch.setattr(_optional, "requires", missing)
    _requirements.cache_clear()


def test_requirements_keep_only_the_extras_own_lines() -> None:
    requirements = _requirements("old")
    assert requirements is not None
    assert [str(r.specifier) for r in requirements] == ["<3,>=2.0"]

    with pytest.raises(ValueError, match="no extra named 'nope'"):
        _requirements("nope")


def test_requirements_are_none_without_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_metadata(monkeypatch)
    assert _requirements("good") is None
    assert _unmet("good") == []


@pytest.mark.parametrize(
    ("extra", "why"),
    [
        ("good", None),
        ("pre", None),  # A pre-release inside the range counts.
        ("old", "found 1.9"),
        ("gone", "not installed"),
        ("far", "not available on this platform"),
        ("farok", None),  # Excluded by its marker, but installed in range.
    ],
)
def test_unmet_names_the_reason(extra: str, why: str | None) -> None:
    assert [reason for _, reason in _unmet(extra)] == ([] if why is None else [why])


def test_has_requirement_checks_one_package() -> None:
    assert _has_requirement("good", "okpkg")
    assert not _has_requirement("old", "oldpkg")
    assert not _has_requirement("gone", "nopkg")

    with pytest.raises(ValueError, match="does not list 'okpkg'"):
        _has_requirement("old", "okpkg")


def test_has_requirement_falls_back_to_presence_without_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_metadata(monkeypatch)
    assert _has_requirement("old", "oldpkg")
    assert not _has_requirement("old", "nopkg")


def test_error_message_names_the_extras_and_what_is_wrong() -> None:
    msg = _build_error_msg(("good", "old"), _unmet("good", "old"))

    assert "pip install -U 'pytrove[good, old]'" in msg
    assert "Required : 'okpkg>=1.0', 'oldpkg<3,>=2.0'" in msg
    assert msg.endswith("Missing  : 'oldpkg<3,>=2.0' (found 1.9)")


async def test_optional_import_passes_through_when_met() -> None:
    @_optional_import("good")
    def sync(x: int) -> int:
        """Double `x`."""
        return x * 2

    @_optional_import("good")
    async def coro() -> int:
        """Return one."""
        return 1

    @_optional_import("good")
    async def agen() -> AsyncIterator[int]:
        """Yield two values."""
        yield 1
        yield 2

    assert sync(2) == 4 and sync.__doc__ == "Double `x`."
    assert inspect.iscoroutinefunction(coro) and await coro() == 1
    assert inspect.isasyncgenfunction(agen)
    assert [i async for i in agen()] == [1, 2]


async def test_optional_import_raises_only_on_call_when_unmet() -> None:
    @_optional_import("old")
    def sync() -> int:
        """Return one."""
        return 1

    @_optional_import("old")
    async def coro() -> int:
        """Return one."""
        return 1

    @_optional_import("old")
    async def agen() -> AsyncIterator[int]:
        """Yield one value."""
        yield 1

    with pytest.raises(ImportError, match=r"found 1\.9"):
        sync()

    with pytest.raises(ImportError, match=r"pytrove\[old\]"):
        await coro()

    with pytest.raises(ImportError, match=r"pytrove\[old\]"):
        [i async for i in agen()]


def test_optional_import_rejects_an_unknown_extra_when_applied() -> None:
    with pytest.raises(ValueError, match="no extra named 'typo'"):
        _optional_import("typo")


def test_unavailable_class_refuses_every_use() -> None:
    stand_in = _unavailable_class("Thing", "gone")
    assert stand_in.__name__ == "Thing"

    for use in (
        stand_in,
        lambda: stand_in.attr,
        lambda: stand_in[int],
        lambda: isinstance(1, stand_in),
        lambda: issubclass(int, stand_in),
        lambda: type("Sub", (stand_in,), {}),
    ):
        with pytest.raises(ImportError, match=r"pytrove\[gone\]"):
            use()


def test_unavailable_class_stays_inspectable() -> None:
    stand_in = _unavailable_class("Thing", "gone")

    # A dunder probe gets `AttributeError`, so `inspect.unwrap` (and with it
    # `doctest` collection over a bare install) walks past the stand-in.
    assert getattr(stand_in, "__wrapped__", None) is None
    assert inspect.unwrap(stand_in) is stand_in

    with pytest.raises(ImportError, match=r"pytrove\[gone\]"):
        _ = stand_in.attr


def test_unavailable_class_refuses_instance_attribute_access() -> None:
    stand_in = _unavailable_class("Thing", "gone")
    # `__new__` refuses, so build the instance past it to reach the instance `__getattr__`.
    instance = object.__new__(stand_in)

    with pytest.raises(ImportError, match=r"pytrove\[gone\]"):
        _ = instance.attr
