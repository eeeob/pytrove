"""`pytrove.constants`: one interface over its modules, and the only home of a public constant."""

from __future__ import annotations as _annotations

import importlib
import inspect
import pkgutil
from typing import TYPE_CHECKING

import pytrove
import pytrove.constants
from pytrove.constants import charsets, lookups, paths, patterns, time_zones

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType


def _public_modules() -> Iterator[ModuleType]:
    for info in pkgutil.walk_packages(pytrove.__path__, "pytrove."):
        if any(part.startswith("_") for part in info.name.split(".")[1:]):
            continue
        try:
            yield importlib.import_module(info.name)
        except ModuleNotFoundError:  # A module that needs an extra which is not installed.
            continue


def test_the_interface_is_the_union_of_its_modules() -> None:
    modules = (paths, patterns, time_zones, lookups, charsets)
    assert pytrove.constants.__all__ == tuple(n for m in modules for n in m.__all__)


def test_every_public_constant_is_defined_in_the_constants_section() -> None:
    # A re-export is fine; what counts is that the object is the one `constants` holds.
    strays = [
        f"{module.__name__}.{name}"
        for module in _public_modules()
        for name in module.__all__
        if name.isupper()
        and not name.startswith("_")  # `_T`, `_P`, ...: the public type variables of `typings`.
        and not inspect.isclass(obj := getattr(module, name))
        and getattr(pytrove.constants, name, None) is not obj
    ]
    assert not strays
