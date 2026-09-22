from __future__ import annotations

import importlib.util
import functools
import operator
import re

from typing import Any, Callable, Final

try:
    from typing import Never
except ImportError:  # Python < 3.11
    from typing_extensions import Never

from importlib.metadata import distribution, version, PackageNotFoundError

from .typings import _P, _T


# A package spec may pin a version the same way a requirement string does --
# "kurigram>=2.2.24", "wrapt>=1.16,<2". Everything up to the first comparison
# operator is the importable/distribution name; the rest is one or more
# comma-separated specifiers, all of which must hold.
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
    """Turn "2.2.24" / "1.16.0rc1" into a comparable tuple of ints.

    Only the numeric release segment is kept -- a trailing pre/post/dev
    suffix is dropped rather than ordered against a final release, since
    these checks exist to catch "too old to have the API we call", not to
    reimplement PEP 440 in full.
    """

    return tuple(
        int(m.group())
        for part in v.split(".")
        if (m := re.match(r"\d+", part))
    )

def _split_spec(spec: str) -> tuple[str, str]:
    """Split "kurigram>=2.2.24" into ("kurigram", ">=2.2.24")."""

    m = _SPEC_RE.match(spec)

    return (spec.strip(), "") if m is None else (m.group(1), m.group(2))

def _version_ok(name: str, clauses: str) -> bool:
    """Check the installed version of `name` against every clause.

    A package with no discoverable version metadata (namespace packages, a
    source checkout on sys.path) passes: the import itself already
    succeeded, and refusing to run over a missing __version__ would be
    stricter than the check is meant to be.
    """

    if not clauses:
        return True

    try:
        installed = _parse_version(version(name))
    except PackageNotFoundError:
        return True

    return all(
        _OPERATORS[op](installed, _parse_version(want))
        for op, want in _CLAUSE_RE.findall(clauses)
    )

def _is_installed(package: str) -> bool:
    """Whether `package` is importable, and satisfies its version pin if it
    carries one -- `package` may be a bare name or a full spec string
    ("kurigram", "kurigram>=2.2.24")."""

    name, clauses = _split_spec(package)

    try:
        distribution(name)
    except PackageNotFoundError:
        # No distribution metadata: fall back to whether the module itself
        # can be found. find_spec() must be given the *name* only -- handing
        # it a full spec raises ModuleNotFoundError rather than returning
        # None, which is why splitting first matters here.
        if importlib.util.find_spec(name) is None:
            return False

    return _version_ok(name, clauses)

def _build_error_msg(
    packages: tuple[tuple[str | tuple[str, ...], str], ...],
    missing: list[tuple[tuple[str, ...], str]],
) -> str:
    all_extras = ", ".join(extra for _, extra in packages)
    all_names = ", ".join(
        f"'{pkg}'" for pkgs, _ in packages
        for pkg in ((pkgs,) if isinstance(pkgs, str) else pkgs)
    )
    missing_names = ", ".join(f"'{pkg}'" for pkgs, _ in missing for pkg in pkgs)

    return (
        f"To use this feature, all required packages must be installed.\n"
        f"Run: pip install 'pytrove[{all_extras}]'\n"
        f"\n"
        f"Required : {all_names}\n"
        f"Missing  : {missing_names}"
    )

def _get_missing(*packages: tuple[str | tuple[str, ...], str]) -> list[tuple[tuple[str, ...], str]]:
    missing: list[tuple[tuple[str, ...], str]] = []

    for pkgs, extra in packages:
        if isinstance(pkgs, str):
            pkgs = (pkgs,)

        missing_in_group = tuple(pkg for pkg in pkgs if not _is_installed(pkg))

        if missing_in_group:
            missing.append((missing_in_group, extra))

    return missing


def _optional_import(*packages: tuple[str | tuple[str, ...], str]) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    missing = _get_missing(*packages)
    error_msg = _build_error_msg(packages, missing) if missing else None

    def decorator(func: Callable[_P, _T]) -> Callable[_P, _T]:
        @functools.wraps(func)
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            if error_msg is not None:
                raise ImportError(error_msg)
            return func(*args, **kwargs)
        return wrapper
    return decorator

def _unavailable_class(name: str, *packages: tuple[str | tuple[str, ...], str]) -> type[Any]:
    """Build a stand-in class for a public class whose optional dependency is
    missing, so the module can still define the name and import cleanly --
    only *using* the class raises, not importing it.

    A plain class with a raising __new__ would stop instantiation but not
    class-level access: `SomeClass.some_attr`, `isinstance(x, SomeClass)`, and
    `class Sub(SomeClass)` would all still silently succeed against a
    half-real class. _UnavailableMeta closes those paths too, by overriding
    the same three operations at the *metaclass* level (__getattr__ for class
    attribute access, __instancecheck__/__subclasscheck__ for isinstance()/
    issubclass()), so every one of them raises the same helpful ImportError
    instead of behaving as if the class were real but empty.
    """

    missing = _get_missing(*packages)

    if not missing:
        raise RuntimeError("No missing packages for unavailable class")

    msg = _build_error_msg(packages, missing)

    class _Unavailable:
        def __new__(cls, *args: Any, **kwargs: Any) -> Never:
            raise ImportError(msg)

        def __getattr__(self, name: str) -> Never:
            raise ImportError(msg)

        def __class_getitem__(cls, item: Any) -> Never:
            raise ImportError(msg)

        @classmethod
        def __init_subclass__(cls, **kwargs: Any) -> Never:
            raise ImportError(msg)

    class _UnavailableMeta(type):
        def __getattr__(cls, name: str) -> Never:
            raise ImportError(msg)

        def __instancecheck__(cls, instance: Any) -> Never:
            raise ImportError(msg)

        def __subclasscheck__(cls, subclass: type[Any]) -> Never:
            raise ImportError(msg)

    return _UnavailableMeta(name, (), dict(_Unavailable.__dict__))