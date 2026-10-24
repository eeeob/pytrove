from __future__ import annotations as _annotations

import importlib
from pathlib import Path

import pytrove._internal
import pytrove.archive_tools._internal
import pytrove.async_tools._internal
import pytrove.data_tools._internal
import pytrove.files_tools._internal
import pytrove.tg_tools._internal
import pytest

PACKAGES = [
    pytrove._internal,
    pytrove.archive_tools._internal,
    pytrove.async_tools._internal,
    pytrove.data_tools._internal,
    pytrove.files_tools._internal,
    pytrove.tg_tools._internal,
]


@pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.__name__)
def test_a_private_package_re_exports_every_module(package: object) -> None:
    root = Path(package.__file__).parent
    modules = [p.stem for p in root.glob("*.py") if p.stem != "__init__"]
    expected = [
        n
        for m in sorted(modules)
        for n in importlib.import_module(f"{package.__name__}.{m}").__all__
    ]
    assert list(package.__all__) == expected
    assert all(hasattr(package, n) for n in expected)


@pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.__name__)
def test_a_private_package_star_import_gives_exactly_its_all(package: object) -> None:
    namespace: dict[str, object] = {}
    exec(f"from {package.__name__} import *", namespace)
    namespace.pop("__builtins__")
    assert set(namespace) == set(package.__all__)
