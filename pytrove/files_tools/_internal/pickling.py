"""Helpers private to `files_tools`: the restricted unpickler behind `read_pickle`."""

from __future__ import annotations as _annotations

import functools
import importlib
import pickle
from pickle import _compat_pickle  # type: ignore[attr-defined, ty:unresolved-import]  # A private stdlib module typeshed does not stub.
from types import ModuleType
from typing import IO, Any, Final

from ...enums import PickleSafety

_SAFE_PICKLE_CLASSES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("builtins", name)
        for name in (
            "bool",
            "bytearray",
            "bytes",
            "complex",
            "dict",
            "float",
            "frozenset",
            "int",
            "list",
            "set",
            "slice",
            "str",
            "tuple",
            "range",
            "NoneType",
            "object",
        )
    }
    | {("collections", name) for name in ("OrderedDict", "defaultdict", "deque", "Counter")}
    | {("datetime", name) for name in ("date", "time", "datetime", "timedelta", "timezone")}
    | {
        ("decimal", "Decimal"),
        ("fractions", "Fraction"),
        ("uuid", "UUID"),
        ("pathlib", "PurePath"),
        ("pathlib", "PurePosixPath"),
        ("pathlib", "PureWindowsPath"),
        ("pathlib", "Path"),
        ("pathlib", "PosixPath"),
        ("pathlib", "WindowsPath"),
        # What protocols 0-2 build `bytes` with: `_codecs.encode(text, "latin1")`.
        ("_codecs", "encode"),
        # What protocols 0-1 build an instance with; it only calls `__new__`/`__init__` of
        # classes that are themselves globals of the stream, so each passed this check too.
        ("copyreg", "_reconstructor"),
    }
)
"""`(module, name)` pairs `read_pickle` always rebuilds: inert data whose construction runs no user code."""

_PICKLE_MODULE_ALIASES: Final[dict[str, str]] = {"pathlib._local": "pathlib"}
"""Private modules a newer Python pickles public classes under, mapped to the public module.

3.13 defines the `pathlib` classes in `pathlib._local`, so a path pickled there
names that module, which no other version has.
"""

_UNSAFE_PICKLE_MODULES: Final[frozenset[str]] = frozenset(
    {
        "os",
        "nt",
        "posix",
        "subprocess",
        "sys",
        "shutil",
        "socket",
        "ctypes",
        "importlib",
        "multiprocessing",
        "pty",
        "runpy",
        "code",
        "codeop",
        "timeit",
        "webbrowser",
        "platform",
        "marshal",
        "pickle",
        "signal",
        "atexit",
        "gc",
        "gettext",
        "gzip",
        "bdb",
        "pdb",
    }
)
"""Modules `PickleSafety.BLOCKLIST` refuses whole: ways to reach the OS, the interpreter or raw memory."""

_UNSAFE_PICKLE_CLASSES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("builtins", name)
        for name in (
            "eval",
            "exec",
            "compile",
            "open",
            "__import__",
            "input",
            "getattr",
            "setattr",
            "delattr",
            "globals",
            "locals",
            "vars",
            "breakpoint",
            "memoryview",
            "staticmethod",
            "classmethod",
            "property",
            "super",
            "type",
            "help",
            "exit",
            "quit",
        )
    }
    | {
        ("operator", "attrgetter"),
        ("operator", "methodcaller"),
        ("operator", "itemgetter"),
        ("functools", "reduce"),
    }
)
"""Individual callables `PickleSafety.BLOCKLIST` refuses: those that evaluate, import or reach attributes."""


class _RestrictedUnpickler(pickle.Unpickler):
    """An unpickler that only rebuilds what its `PickleSafety` level permits.

    `find_class` is the one door every global lookup goes through, so refusing
    there stops a pickle from naming `os.system` and having it called.
    """

    def __init__(
        self,
        file: IO[bytes],
        level: PickleSafety,
        allowed: frozenset[tuple[str, str]],
        allowed_modules: frozenset[str],
        **kw: Any,
    ) -> None:
        """Set up the unpickler.

        Args:
            file: The pickle stream.
            level: How much to allow; never `PickleSafety.NONE`.
            allowed: `(module, name)` pairs allowed at every level.
            allowed_modules: Modules allowed at `PickleSafety.MODULES`.
            **kw: `pickle.Unpickler` keyword arguments.
        """
        super().__init__(file, **kw)
        self._level = level
        self._allowed = allowed
        self._allowed_modules = allowed_modules

    def _permits(self, module: str, name: str) -> bool:
        """Decide, before importing anything, on the pair pickle will actually import.

        Args:
            module: The module, after `_normalise_global`.
            name: The global, after `_normalise_global`.

        Returns:
            Whether this level allows looking it up.
        """
        if (module, name) in self._allowed:
            return True

        if self._level >= PickleSafety.STRICT:
            return False

        if self._level >= PickleSafety.MODULES:
            return module in self._allowed_modules

        return module not in _UNSAFE_PICKLE_MODULES and (module, name) not in _UNSAFE_PICKLE_CLASSES

    def find_class(self, module: str, name: str) -> Any:
        """Return the named global, if this level allows it.

        Args:
            module: The module named in the stream.
            name: The global named in the stream.

        Returns:
            The global.

        Raises:
            pickle.UnpicklingError: If the level refuses it.
        """
        module, name = _normalise_global(module, name)

        if self._permits(module, name):
            found = super().find_class(module, name)
            own = _defining_module(found) == module

            # From protocol 4 a dotted name walks attributes, so `shutil` + `os.system`
            # reaches `os` through `shutil.os`; and `MODULES` allows what a module
            # defines, not what it imports. Either way, the object has to come from
            # the module the stream names, unless the pair was allowed outright.
            # `BLOCKLIST` also judges the object itself: a plain `shutil.os` is `os`.
            if (module, name) in self._allowed:
                return found

            if self._level >= PickleSafety.MODULES:
                if own:
                    return found
            elif ("." not in name or own) and not _is_blocked_object(found):
                return found

        msg = (
            f"read_pickle: refusing to load '{module}.{name}' at safety level {self._level.name} -- "
            f"if this file is yours and '{name}' is a class that is safe to construct, pass it in "
            f"`allow_classes`; for a file you fully control, lower `safe` (see PickleSafety)."
        )
        raise pickle.UnpicklingError(msg)


def _defining_module(found: object) -> str | None:
    """Name the public module that defines `found`, as `__module__` gives it.

    Args:
        found: An object `find_class` looked up.

    Returns:
        The module, mapped through `_PICKLE_MODULE_ALIASES`, or `None` when
        `found` names none (a bound builtin method, a dict, a str).
    """
    module = getattr(found, "__module__", None)
    return _PICKLE_MODULE_ALIASES.get(module, module) if isinstance(module, str) else None


@functools.cache
def _blocked_callable_ids() -> frozenset[int]:
    """Resolve `_UNSAFE_PICKLE_CLASSES` once, so each callable is known by identity.

    Returns:
        The `id` of every blocked callable this interpreter has; `help`, `exit`
        and `quit` exist only when `site` ran.
    """
    found = (getattr(importlib.import_module(m), n, None) for m, n in _UNSAFE_PICKLE_CLASSES)
    return frozenset(id(obj) for obj in found if obj is not None)


def _is_blocked_object(found: object) -> bool:
    """Tell whether `PickleSafety.BLOCKLIST` refuses `found`, whatever name reached it.

    A module can hand out another one (`shutil.os` is `os`) or re-export a
    builtin (`io.open` is `builtins.open`), so the names alone are not enough.

    Args:
        found: An object `find_class` looked up.

    Returns:
        Whether it is, or is defined in, a module of `_UNSAFE_PICKLE_MODULES`
        (or one of their submodules), or is a callable of `_UNSAFE_PICKLE_CLASSES`.
    """
    origin = found.__name__ if isinstance(found, ModuleType) else _defining_module(found)

    if origin is not None and origin.partition(".")[0] in _UNSAFE_PICKLE_MODULES:
        return True

    return id(found) in _blocked_callable_ids()


def _normalise_global(module: str, name: str) -> tuple[str, str]:
    """Map a module/name pair to the public one pickle should import.

    Protocols 0-2 store `__builtin__.set` for `builtins.set`. Checking the
    untranslated pair would be a hole: `__builtin__.eval` would slip past the
    blocklist entry for `builtins.eval`. A private module from
    `_PICKLE_MODULE_ALIASES` maps to its public one, so a path pickled on 3.13
    is judged, and loaded, as `pathlib.Path` on every version.

    Args:
        module: The module named in the stream.
        name: The global named in the stream.

    Returns:
        The translated pair, or the original when no mapping applies.
    """
    key = (module, name)

    if key in _compat_pickle.NAME_MAPPING:
        return _compat_pickle.NAME_MAPPING[key]

    if module in _compat_pickle.IMPORT_MAPPING:
        return _compat_pickle.IMPORT_MAPPING[module], name

    if module in _PICKLE_MODULE_ALIASES:
        return _PICKLE_MODULE_ALIASES[module], name

    return key


__all__ = (
    "_RestrictedUnpickler",
    "_blocked_callable_ids",
    "_defining_module",
    "_is_blocked_object",
    "_normalise_global",
    "_PICKLE_MODULE_ALIASES",
    "_SAFE_PICKLE_CLASSES",
    "_UNSAFE_PICKLE_CLASSES",
    "_UNSAFE_PICKLE_MODULES",
)
