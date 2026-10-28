"""The single gate between a feature and the optional dependency it needs."""

from __future__ import annotations as _annotations

import contextlib
import functools
import inspect
import sys
from importlib.metadata import PackageNotFoundError, requires, version
from typing import TYPE_CHECKING, Any, cast

if sys.version_info >= (3, 11):
    from typing import Never
else:
    from typing_extensions import Never

from packaging.requirements import Requirement
from packaging.version import InvalidVersion

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from ..typings import _P, _T


@functools.cache
def _requirements(extra: str) -> tuple[Requirement, ...] | None:
    """Read the requirements `extra` installs from pytrove's own metadata.

    `pyproject.toml` is the one place versions are written: it becomes the
    `Requires-Dist` lines read here, so no feature repeats a version.

    Args:
        extra: The extra's name, such as `"proxy"`.

    Returns:
        Its requirements, those its markers exclude on this platform included,
        or `None` when pytrove has no installed metadata (a source tree on
        `sys.path`), in which case nothing can be checked.

    Raises:
        ValueError: If pytrove declares no extra by that name.
    """
    try:
        lines = requires("pytrove") or []
    except PackageNotFoundError:
        return None

    # `packaging` normalises every marker to this spelling, whatever `pyproject.toml` wrote.
    member = f'extra == "{extra}"'
    found = tuple(
        r for r in map(Requirement, lines) if r.marker is not None and member in str(r.marker)
    )

    if not found:
        msg = f"pytrove declares no extra named {extra!r}"
        raise ValueError(msg)

    return found


def _why_unmet(requirement: Requirement, extra: str) -> str | None:
    """Tell why `requirement` cannot be used here, if it cannot.

    One its marker excludes on this platform is still used when installed in
    range: `zstandard` serves a 3.14 built without `compression.zstd`.

    Args:
        requirement: One requirement of `extra`.
        extra: The extra it belongs to.

    Returns:
        The reason, or `None` when the installed version is in range. A version
        `packaging` cannot parse counts as out of range rather than crashing the
        import that runs this check.
    """
    try:
        found = version(requirement.name)
    except PackageNotFoundError:
        if requirement.marker is not None and not requirement.marker.evaluate({"extra": extra}):
            return "not available on this platform"
        return "not installed"

    # `packaging` before 26 raises on a non-PEP 440 version; 26 returns `False`.
    try:
        in_range = requirement.specifier.contains(found, prereleases=True)
    except InvalidVersion:
        in_range = False

    if not in_range:
        return f"found {found}"

    return None


@functools.cache
def _unmet(*extras: str) -> tuple[tuple[Requirement, str], ...]:
    """Return each requirement of `extras` that cannot be used here, with the reason.

    Cached like `_requirements`: every gated function of an extra asks the same
    question at import, and the installed versions do not change in between.

    Args:
        *extras: The extras' names.

    Returns:
        The unusable requirements and why; empty when pytrove has no metadata.
    """
    return tuple(
        (requirement, why)
        for extra in extras
        for requirement in _requirements(extra) or ()
        if (why := _why_unmet(requirement, extra)) is not None
    )


def _has_requirement(extra: str, name: str) -> bool:
    """Tell whether the package `name` of `extra` is installed in the range `extra` asks for.

    For a module that imports the package itself: importable is not enough,
    since a user may have installed an older release outside the extra.

    Args:
        extra: The extra's name.
        name: The distribution's name, as `pyproject.toml` writes it.

    Returns:
        Whether it is usable; without pytrove's metadata, whether it is installed.

    Raises:
        ValueError: If `extra` does not list `name`.
    """
    requirements = _requirements(extra)

    if requirements is None:
        try:
            version(name)
        except PackageNotFoundError:
            return False
        return True

    for requirement in requirements:
        if requirement.name == name:
            return _why_unmet(requirement, extra) is None

    msg = f"the {extra!r} extra does not list {name!r}"
    raise ValueError(msg)


def _build_error_msg(extras: tuple[str, ...], unmet: tuple[tuple[Requirement, str], ...]) -> str:
    """Build the message raised when a feature's requirements are not met.

    Args:
        extras: Every extra the feature needs.
        unmet: The requirements that are not met, with the reason.

    Returns:
        The message, with the `pip install` command covering every extra. The
        `Required` and `Missing` lines are left out when empty, as they are
        without pytrove's metadata, where nothing can be listed.
    """
    required = ", ".join(
        f"'{r.name}{r.specifier}'" for extra in extras for r in _requirements(extra) or ()
    )
    missing = ", ".join(f"'{r.name}{r.specifier}' ({why})" for r, why in unmet)
    details = [f"Required : {required}"] if required else []
    details += [f"Missing  : {missing}"] if missing else []

    return "\n".join(
        [
            "To use this feature, all required packages must be installed.",
            f"Run: pip install -U 'pytrove[{', '.join(extras)}]'",
            *([""] + details if details else []),
        ]
    )


def _optional_import(*extras: str) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    """Gate a sync, async or async-generator function on the requirements of `extras`.

    What is unmet is computed once, when the decorator is applied; the
    `ImportError` is raised only when the function is called.

    Args:
        *extras: The extras the function needs, such as `"proxy"`.

    Returns:
        The decorator.
    """
    unmet = _unmet(*extras)
    error_msg = _build_error_msg(extras, unmet) if unmet else None

    def decorator(func: Callable[_P, _T]) -> Callable[_P, _T]:
        """Wrap `func` so a call raises while its requirements are unmet."""
        if inspect.isasyncgenfunction(func):

            @functools.wraps(func)
            async def agen_wrapper(*args: _P.args, **kwargs: _P.kwargs) -> AsyncIterator[Any]:
                """Raise if requirements are unmet, otherwise yield from `func`."""
                if error_msg is not None:
                    raise ImportError(error_msg)
                # `aclosing` closes `func`'s generator as soon as the caller stops early,
                # so its `finally` runs then rather than whenever the loop finalises it.
                async with contextlib.aclosing(func(*args, **kwargs)) as gen:
                    async for item in gen:
                        yield item

            # `async def` types the wrapper as returning a `Coroutine` around its result,
            # while `_T` already is the awaitable `func` returns; the parameters match.
            return cast("Callable[_P, _T]", agen_wrapper)

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def coro_wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
                """Raise if requirements are unmet, otherwise await `func`."""
                if error_msg is not None:
                    raise ImportError(error_msg)
                return await func(*args, **kwargs)

            # `async def` types the wrapper as returning a `Coroutine` around its result,
            # while `_T` already is the awaitable `func` returns; the parameters match.
            return cast("Callable[_P, _T]", coro_wrapper)

        @functools.wraps(func)
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            """Raise if requirements are unmet, otherwise call `func`."""
            if error_msg is not None:
                raise ImportError(error_msg)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def _unavailable_class(name: str, *extras: str) -> type[Any]:
    """Build a stand-in for a public class whose optional dependency is unusable.

    The module can still define the name and import cleanly; only using the
    class raises. A raising `__new__` alone would leave `SomeClass.attr`,
    `isinstance(x, SomeClass)` and `class Sub(SomeClass)` silently working,
    so the metaclass overrides `__getattr__`, `__instancecheck__` and
    `__subclasscheck__` to raise the same `ImportError`.

    The stand-in reports the caller's module as its `__module__` and the error
    message as its `__doc__`, so `help()` on it explains what to install.

    Args:
        name: The class name.
        *extras: The extras the class needs.

    Returns:
        The stand-in class.
    """
    msg = _build_error_msg(extras, _unmet(*extras))
    module = sys._getframe(1).f_globals.get("__name__", __name__)

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

    namespace = {
        **_Unavailable.__dict__,
        "__module__": module,
        "__doc__": msg,
        "__qualname__": name,
    }
    return _UnavailableMeta(name, (), namespace)


__all__ = (
    "_build_error_msg",
    "_has_requirement",
    "_optional_import",
    "_unavailable_class",
    "_unmet",
)
