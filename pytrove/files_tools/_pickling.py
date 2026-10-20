"""Helpers private to `files_tools`: the restricted unpickler behind `read_pickle`."""

from __future__ import annotations as _annotations

import pickle
from pickle import _compat_pickle  # type: ignore[attr-defined, ty:unresolved-import]  # A private stdlib module typeshed does not stub.
from typing import IO, Any, Final

from ..enums import PickleSafety

_SAFE_PICKLE_CLASSES: Final[frozenset[tuple[str, str]]] = frozenset(
    {("builtins", name) for name in (
        "bool", "bytearray", "bytes", "complex", "dict", "float", "frozenset", "int", "list", "set",
        "slice", "str", "tuple", "range", "NoneType", "object",
    )}
    | {("collections", name) for name in ("OrderedDict", "defaultdict", "deque", "Counter", "namedtuple")}
    | {("datetime", name) for name in ("date", "time", "datetime", "timedelta", "timezone")}
    | {
        ("decimal", "Decimal"), ("fractions", "Fraction"), ("uuid", "UUID"),
        ("pathlib", "PurePath"), ("pathlib", "PurePosixPath"), ("pathlib", "PureWindowsPath"),
        ("pathlib", "Path"), ("pathlib", "PosixPath"), ("pathlib", "WindowsPath"),
    }
)
"""`(module, name)` pairs `read_pickle` always rebuilds: inert data whose construction runs no user code."""

_UNSAFE_PICKLE_MODULES: Final[frozenset[str]] = frozenset({
    "os", "nt", "posix", "subprocess", "sys", "shutil", "socket", "ctypes", "importlib", "multiprocessing",
    "pty", "runpy", "code", "codeop", "timeit", "webbrowser", "platform", "marshal", "pickle", "signal",
    "atexit", "gc", "gettext", "gzip", "bdb", "pdb",
})
"""Modules `PickleSafety.BLOCKLIST` refuses whole: ways to reach the OS, the interpreter or raw memory."""

_UNSAFE_PICKLE_CLASSES: Final[frozenset[tuple[str, str]]] = frozenset(
    {("builtins", name) for name in (
        "eval", "exec", "compile", "open", "__import__", "input", "getattr", "setattr", "delattr", "globals",
        "locals", "vars", "breakpoint", "memoryview", "staticmethod", "classmethod", "property", "super",
        "type", "help", "exit", "quit",
    )}
    | {("operator", "attrgetter"), ("operator", "methodcaller"), ("operator", "itemgetter"), ("functools", "reduce")}
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
        """Decide on the pair pickle will actually import, after Python 2 name mapping.

        Args:
            module: The module named in the stream.
            name: The global named in the stream.

        Returns:
            Whether this level allows it.
        """
        module, name = _normalise_global(module, name)

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
        if self._permits(module, name):
            return super().find_class(module, name)

        msg = (
            f"read_pickle: refusing to load '{module}.{name}' at safety level {self._level.name} -- pass "
            f"allow_classes=[{name}] if this file is yours and the class is safe to construct, or lower "
            f"`safe` (see PickleSafety) for a file you fully control."
        )
        raise pickle.UnpicklingError(msg)


def _normalise_global(module: str, name: str) -> tuple[str, str]:
    """Map a Python 2 module/name pair to the Python 3 one pickle will import.

    Protocols 0-2 store `__builtin__.set` for `builtins.set`. Checking the
    untranslated pair would be a hole: `__builtin__.eval` would slip past the
    blocklist entry for `builtins.eval`.

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

    return key


__all__ = (
    "_RestrictedUnpickler",
    "_normalise_global",
    "_SAFE_PICKLE_CLASSES",
    "_UNSAFE_PICKLE_CLASSES",
    "_UNSAFE_PICKLE_MODULES",
)
