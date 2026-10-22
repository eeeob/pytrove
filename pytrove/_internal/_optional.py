"""The single gate between a feature and the optional dependency it needs."""

from __future__ import annotations as _annotations

import functools
import importlib.util
import inspect
import operator
import re
import sys
from collections.abc import AsyncIterator, Callable
from importlib.metadata import PackageNotFoundError, distribution, version
from typing import Any, Final, TypeAlias, cast

if sys.version_info >= (3, 11):
    from typing import Never
else:
    from typing_extensions import Never

from ..typings import _P, _T

_PackageGroup: TypeAlias = tuple[str | tuple[str, ...], str]
"""One or more package specs, and the extra that installs them."""

# A package spec may pin a version the same way a requirement string does:
# `"kurigram>=2.2.24"`, `"wrapt>=1.16,<2"`. Everything up to the first comparison
# operator is the distribution name; the rest is one or more comma-separated
# specifiers, all of which must hold.
_SPEC_RE: Final[re.Pattern[str]] = re.compile(r"^\s*([^<>=!~\s]+)\s*(.*)$")
_CLAUSE_RE: Final[re.Pattern[str]] = re.compile(r"(==|!=|>=|<=|~=|>|<)\s*([^,\s]+)")

_OPERATORS: Final[dict[str, Callable[[Any, Any], bool]]] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
}


def _parse_version(v: str) -> tuple[int, ...]:
    """Turn `"2.2.24"` or `"1.16.0rc1"` into a comparable tuple of ints.

    Only the numeric release segment is kept: a pre/post/dev suffix is
    dropped rather than ordered against a final release, since these checks
    catch "too old to have the API we call", not all of PEP 440.

    Args:
        v: The version string.

    Returns:
        The numeric segments.
    """
    return tuple(int(m.group()) for part in v.split(".") if (m := re.match(r"\d+", part)))


def _split_spec(spec: str) -> tuple[str, str]:
    """Split `"kurigram>=2.2.24"` into `("kurigram", ">=2.2.24")`.

    Args:
        spec: A bare name or a pinned spec.

    Returns:
        The name and its version clauses, empty if none.
    """
    m = _SPEC_RE.match(spec)

    return (spec.strip(), "") if m is None else (m.group(1), m.group(2))


def _version_ok(name: str, clauses: str) -> bool:
    """Check the installed version of `name` against every clause.

    A package with no version metadata (a namespace package, a source
    checkout on `sys.path`) passes: it was found, and refusing it over
    missing metadata would be stricter than the check is meant to be.

    Args:
        name: The distribution name.
        clauses: The version clauses, such as `">=1.16,<2"`.

    Returns:
        Whether every clause holds.
    """
    if not clauses:
        return True

    try:
        installed = _parse_version(version(name))
    except PackageNotFoundError:
        return True

    return all(_OPERATORS[op](installed, _parse_version(want)) for op, want in _CLAUSE_RE.findall(clauses))


def _is_installed(package: str) -> bool:
    """Return whether `package` is installed and satisfies its version pin, if any.

    Args:
        package: A bare name or a pinned spec (`"kurigram"`, `"kurigram>=2.2.24"`).

    Returns:
        Whether the package is usable.
    """
    name, clauses = _split_spec(package)

    try:
        distribution(name)
    except PackageNotFoundError:
        # No distribution metadata: fall back to whether the module itself
        # can be found. `find_spec()` must be given the name only: a full spec
        # raises `ModuleNotFoundError` instead of returning `None`.
        if importlib.util.find_spec(name) is None:
            return False

    return _version_ok(name, clauses)


def _build_error_msg(packages: tuple[_PackageGroup, ...], missing: list[tuple[tuple[str, ...], str]]) -> str:
    """Build the message raised when a feature's packages are missing.

    Args:
        packages: Every package group the feature needs.
        missing: The groups, narrowed to their missing packages.

    Returns:
        The message, with the `pip install` command covering every extra.
    """
    all_extras = ", ".join(extra for _, extra in packages)
    all_names = ", ".join(f"'{pkg}'" for pkgs, _ in packages for pkg in ((pkgs,) if isinstance(pkgs, str) else pkgs))
    missing_names = ", ".join(f"'{pkg}'" for pkgs, _ in missing for pkg in pkgs)

    return (
        f"To use this feature, all required packages must be installed.\n"
        f"Run: pip install 'pytrove[{all_extras}]'\n"
        f"\n"
        f"Required : {all_names}\n"
        f"Missing  : {missing_names}"
    )


def _get_missing(*packages: _PackageGroup) -> list[tuple[tuple[str, ...], str]]:
    """Return each package group narrowed to its missing packages, dropping complete groups.

    Args:
        *packages: The package groups.

    Returns:
        The incomplete groups, each with only its missing packages.
    """
    missing: list[tuple[tuple[str, ...], str]] = []

    for pkgs, extra in packages:
        group = (pkgs,) if isinstance(pkgs, str) else pkgs
        missing_in_group = tuple(pkg for pkg in group if not _is_installed(pkg))

        if missing_in_group:
            missing.append((missing_in_group, extra))

    return missing


def _optional_import(*packages: _PackageGroup) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    """Gate a sync, async or async-generator function on optional packages.

    What is missing is computed once, when the decorator is applied; the
    `ImportError` is raised only when the function is called.

    Args:
        *packages: The package groups the function needs.

    Returns:
        The decorator.
    """
    missing = _get_missing(*packages)
    error_msg = _build_error_msg(packages, missing) if missing else None

    def decorator(func: Callable[_P, _T]) -> Callable[_P, _T]:
        """Wrap `func` so a call raises while its packages are missing."""
        if inspect.isasyncgenfunction(func):

            @functools.wraps(func)
            async def agen_wrapper(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
                """Raise if packages are missing, otherwise yield from `func`."""
                if error_msg is not None:
                    raise ImportError(error_msg)
                async for item in func(*args, **kwargs):
                    yield item

            # Same parameters and result as `func`, which is what `Callable[_P, _T]` states.
            return cast(Callable[_P, _T], agen_wrapper)

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def coro_wrapper(*args: Any, **kwargs: Any) -> Any:
                """Raise if packages are missing, otherwise await `func`."""
                if error_msg is not None:
                    raise ImportError(error_msg)
                return await func(*args, **kwargs)

            # Same parameters and result as `func`, which is what `Callable[_P, _T]` states.
            return cast(Callable[_P, _T], coro_wrapper)

        @functools.wraps(func)
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            """Raise if packages are missing, otherwise call `func`."""
            if error_msg is not None:
                raise ImportError(error_msg)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def _unavailable_class(name: str, *packages: _PackageGroup) -> type[Any]:
    """Build a stand-in for a public class whose optional dependency is missing.

    The module can still define the name and import cleanly; only using the
    class raises. A raising `__new__` alone would leave `SomeClass.attr`,
    `isinstance(x, SomeClass)` and `class Sub(SomeClass)` silently working,
    so the metaclass overrides `__getattr__`, `__instancecheck__` and
    `__subclasscheck__` to raise the same `ImportError`.

    Args:
        name: The class name.
        *packages: The package groups the class needs.

    Returns:
        The stand-in class.

    Raises:
        RuntimeError: If nothing is actually missing.
    """
    missing = _get_missing(*packages)

    if not missing:
        msg = "No missing packages for unavailable class"
        raise RuntimeError(msg)

    msg = _build_error_msg(packages, missing)

    class _Unavailable:
        """The body every operation on the stand-in raises from."""

        def __new__(cls, *args: Any, **kwargs: Any) -> Never:
            """Refuse to instantiate."""
            raise ImportError(msg)

        def __getattr__(self, name: str) -> Never:
            """Refuse instance attribute access."""
            raise ImportError(msg)

        def __class_getitem__(cls, item: Any) -> Never:
            """Refuse subscription."""
            raise ImportError(msg)

        @classmethod
        def __init_subclass__(cls, **kwargs: Any) -> Never:
            """Refuse subclassing."""
            raise ImportError(msg)

    class _UnavailableMeta(type):
        """Makes class-level access raise too."""

        def __getattr__(cls, name: str) -> Never:
            """Refuse class attribute access.

            A dunder lookup gets the `AttributeError` introspection expects:
            `inspect.unwrap` probes `__wrapped__`, and `doctest` and `pydoc`
            walk every public name of a module, so raising `ImportError` there
            would make a bare install uninspectable rather than unusable.
            """
            if name.startswith("__") and name.endswith("__"):
                raise AttributeError(name)
            raise ImportError(msg)

        def __instancecheck__(cls, instance: Any) -> Never:
            """Refuse `isinstance()`."""
            raise ImportError(msg)

        def __subclasscheck__(cls, subclass: type[Any]) -> Never:
            """Refuse `issubclass()`."""
            raise ImportError(msg)

    return _UnavailableMeta(name, (), dict(_Unavailable.__dict__))


__all__ = ("_optional_import", "_unavailable_class")
