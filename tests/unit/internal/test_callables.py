"""`_internal._callables`: `_ignore_arguments`."""

from __future__ import annotations as _annotations

import ast
from pathlib import Path

import pytrove
from pytrove._internal import _ignore_arguments


def test_ignore_arguments_calls_the_function_with_none_of_the_arguments() -> None:
    calls: list[str] = []

    def make() -> str:
        """Record the call."""
        calls.append("made")
        return "value"

    wrapped = _ignore_arguments(make)

    assert wrapped(1, 2, key=3) == "value"
    assert wrapped() == "value"
    assert calls == ["made", "made"]


def test_ignore_arguments_keeps_the_functions_metadata() -> None:
    def make() -> int:
        """The factory's own docstring."""
        return 0

    wrapped = _ignore_arguments(make)

    assert wrapped.__name__ == "make"
    assert wrapped.__doc__ == "The factory's own docstring."
    assert getattr(wrapped, "__wrapped__", None) is make


def test_data_tools_imports_neither_callable_tools_nor_async_tools_at_module_level() -> None:
    # Why the helper lives here: `object_tools` imports `data_tools`, and
    # `async_tools` imports `object_tools` at module top, so a module-level
    # `data_tools` import reaching `callable_tools` (which imports `async_tools`)
    # would close a cycle.
    root = Path(pytrove.__file__).parent
    reached = set()

    for path in (root / "data_tools").rglob("*.py"):
        package = ".".join(("pytrove", *path.relative_to(root).with_suffix("").parts))
        package = package if path.name == "__init__.py" else package.rpartition(".")[0]
        package = package.removesuffix(".__init__")

        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ImportFrom):
                base = package.split(".")
                target = (
                    ".".join(base[: len(base) - node.level + 1] + [node.module or ""])
                    if node.level
                    else node.module or ""
                )
                reached.add(target.rstrip("."))

    assert not {
        m for m in reached if m.startswith(("pytrove.callable_tools", "pytrove.async_tools"))
    }
