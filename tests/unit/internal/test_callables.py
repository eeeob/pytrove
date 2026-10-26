"""`_internal._callables`: `_ignore_arguments` and `_iter_unwrap_layers`."""

from __future__ import annotations as _annotations

import ast
import functools
import sys
from pathlib import Path
from typing import Any

import pytest

import pytrove
from pytrove._internal import _ignore_arguments, _iter_unwrap_layers


def _base(self: Any, x: int = 0) -> int:
    """Return `x`."""
    return x


def _decorate(func: Any) -> Any:
    """Wrap `func` with `functools.wraps`."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Call `func`."""
        return func(*args, **kwargs)

    return wrapper


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


def test_iter_unwrap_layers_yields_every_layer_outermost_first() -> None:
    inner = _decorate(_base)
    partial = functools.partial(inner, None)
    prop = property(partial)

    assert list(_iter_unwrap_layers(prop, with_prop=True)) == [prop, partial, inner, _base]


@pytest.mark.parametrize(
    "build",
    [
        lambda f: functools.partial(_decorate(f), None),
        lambda f: _decorate(functools.partial(f, None)),
        lambda f: property(functools.partial(_decorate(f), None)),
        lambda f: _decorate(property(f)),
        lambda f: functools.partialmethod(_decorate(f), 1),
        lambda f: _decorate(functools.partialmethod(f, 1)),
        lambda f: property(_decorate(functools.partialmethod(_decorate(f), 1))),
    ],
    ids=[
        "partial-of-wraps",
        "wraps-of-partial",
        "property-of-partial-of-wraps",
        "wraps-of-property",
        "partialmethod-of-wraps",
        "wraps-of-partialmethod",
        "property-of-wraps-of-partialmethod-of-wraps",
    ],
)
def test_iter_unwrap_layers_peels_any_nesting_order(build: Any) -> None:
    *_, innermost = _iter_unwrap_layers(build(_base), with_prop=True)

    assert innermost is _base


def test_iter_unwrap_layers_keeps_a_property_without_with_prop() -> None:
    prop = property(_decorate(_base))

    assert list(_iter_unwrap_layers(prop, with_prop=False)) == [prop]


def test_iter_unwrap_layers_ends_on_none_for_a_property_without_a_getter() -> None:
    prop = property()

    assert list(_iter_unwrap_layers(prop, with_prop=True)) == [prop, None]


def test_iter_unwrap_layers_never_peels_a_class() -> None:
    class Proxyish:
        """Carries `__wrapped__` as a class-level property, like a `wrapt` proxy."""

        @property
        def __wrapped__(self) -> int:
            """The wrapped value."""
            return 1

    assert list(_iter_unwrap_layers(Proxyish, with_prop=True)) == [Proxyish]


def test_iter_unwrap_layers_raises_on_a_loop_across_kinds() -> None:
    def func() -> None:
        """Wrap a property of itself."""

    func.__wrapped__ = property(func)

    with pytest.raises(ValueError, match="wrapper loop when unwrapping"):
        list(_iter_unwrap_layers(func, with_prop=True))


def test_iter_unwrap_layers_raises_past_the_recursion_limit() -> None:
    class Endless:
        """Wraps a fresh instance of itself on every access."""

        @property
        def __wrapped__(self) -> Endless:
            """A new layer."""
            return Endless()

    layers = _iter_unwrap_layers(Endless(), with_prop=True)

    with pytest.raises(ValueError, match="wrapper loop when unwrapping"):
        for count, _ in enumerate(layers):
            assert count <= sys.getrecursionlimit()


def test_iter_unwrap_layers_is_lazy() -> None:
    def func() -> None:
        """Wrap itself."""

    func.__wrapped__ = func
    outer = _decorate(func)
    layers = _iter_unwrap_layers(outer, with_prop=True)

    assert next(layers) is outer
    assert next(layers) is func
