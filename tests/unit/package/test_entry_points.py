from __future__ import annotations as _annotations

import importlib
import re
from collections import Counter
from pathlib import Path

import pytest

import pytrove
import pytrove.object_tools
import pytrove.enums
import pytrove.errors
import pytrove.models
import pytrove.typings

ENTRY_POINTS = ["pytrove", "pytrove.typings", "pytrove.errors", "pytrove.models", "pytrove.enums"]

# The type variables and literals in `typings` are public by design; the underscore marks them as aliases.
PUBLIC_UNDERSCORE_TYPES = {
    "_P",
    "_T",
    "_CT",
    "_FT",
    "_KT",
    "_VT",
    "_True",
    "_False",
    "_EnumT",
    "_ExcT",
}


@pytest.mark.parametrize("name", ENTRY_POINTS)
def test_star_import_gives_exactly_the_declared_public_names(name: str) -> None:
    namespace: dict[str, object] = {}
    exec(f"from {name} import *", namespace)
    namespace.pop("__builtins__")
    assert set(namespace) == set(importlib.import_module(name).__all__)


@pytest.mark.parametrize("name", ENTRY_POINTS)
def test_entry_point_names_are_unique_and_public(name: str) -> None:
    names = importlib.import_module(name).__all__
    assert not [n for n, count in Counter(names).items() if count > 1]
    assert not [n for n in names if n.startswith("_") and n not in PUBLIC_UNDERSCORE_TYPES]


def test_tools_entry_point_holds_no_type_error_model_or_enum() -> None:
    others = {
        *pytrove.typings.__all__,
        *pytrove.errors.__all__,
        *pytrove.models.__all__,
        *pytrove.enums.__all__,
    }
    assert not set(pytrove.__all__) & others


@pytest.mark.parametrize(
    "package", [pytrove, pytrove.object_tools, pytrove.models, pytrove.typings]
)
def test_an_aggregator_is_the_union_of_its_modules(package: object) -> None:
    root = Path(package.__file__).parent
    modules = [
        p.stem for p in root.glob("*.py") if p.stem != "__init__" and not p.stem.startswith("_")
    ]
    modules += [
        p.name
        for p in root.iterdir()
        if (p / "__init__.py").is_file() and not p.name.startswith("_")
    ]
    if package is pytrove:
        modules = [m for m in modules if m not in {"enums", "errors", "models", "typings"}]
    expected = {
        n for m in modules for n in importlib.import_module(f"{package.__name__}.{m}").__all__
    }
    assert set(package.__all__) == expected


def test_version_is_a_release_string_hatch_can_read() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", pytrove.__version__)
    source = Path(pytrove.__file__).read_text(encoding="utf-8")
    # hatchling's default `[tool.hatch.version]` pattern.
    match = re.search(
        r"""^(__version__|VERSION) *= *(['"])v?(?P<version>.+?)\2""", source, re.MULTILINE
    )
    assert match
    assert match["version"] == pytrove.__version__
