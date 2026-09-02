import json
import os
import pickle

from pathlib import Path
from pickle import _compat_pickle  # type: ignore[attr-defined]
from typing import Any, Dict, FrozenSet, Tuple, Union
from .enums import PickleSafety

try:
    import orjson
except ImportError:
    HAS_ORJSON = False
else:
    HAS_ORJSON = True


_NOT_SET = object()

#: How much of a file is held in memory while it is copied from one place
#: to another. One buffer per copy, so a 4 GB file costs this and not its
#: own size.
_COPY_BUF = 1 << 20


def _next_part(folder: "Path", stem: str) -> int:
    """The first free number for a "<stem>.N" part file in `folder`.

    One past the highest that is already there, rather than 1, so a second
    truncation of the same file adds parts instead of writing over the
    ones the first produced. Losing those is exactly what a caller asking
    for parts is asking not to happen.

    A number is only a number if the whole suffix is digits: "app.log.2"
    counts and "app.log.bak" does not, so an unrelated neighbour cannot
    push the count up or, worse, be counted as a part and later read back
    as one.
    """

    highest = 0
    prefix = f"{stem}."

    try:
        names = os.listdir(folder)
    except OSError:
        return 1

    for name in names:
        if not name.startswith(prefix):
            continue

        tail = name[len(prefix):]

        if tail.isdigit():
            highest = max(highest, int(tail))

    return highest + 1


# orjson is 10x faster than json at dumping, but it is not a drop-in: it
# takes no keyword arguments beyond `default` and `option` flags, only ever
# indents by 2, never escapes to ASCII, and hands back bytes. So it is used
# only when the caller's kwargs happen to be expressible in it, and json
# serves everything else.
#
# The fast path never changes the parsed value, only the bytes: orjson has
# no separator setting, so its compact form is `{"a":1}` where json writes
# `{"a": 1}`. Anything comparing JSON files byte-for-byte (a checksum, a
# golden-file test) should pin `indent` rather than rely on the default.
_ORJSON_DUMP_KEYS = frozenset({"ensure_ascii", "indent", "sort_keys", "default"})

if HAS_ORJSON:
    # orjson serialises datetime/date/time and dataclasses natively, which
    # json does not -- left alone, the same call would produce different
    # output (or succeed instead of raising) purely because the extra was
    # installed. These two flags hand those types back to `default`, or to
    # a TypeError when there is none, exactly as json does.
    #
    # OPT_PASSTHROUGH_SUBCLASS is deliberately NOT set: json serialises
    # str/int subclasses natively, so passing those through would be the
    # divergence rather than the fix.
    #
    # OPT_NON_STR_KEYS closes the same gap from the other side -- json
    # stringifies int/float/bool/None dict keys, and orjson refuses them
    # outright without this flag. With it the two agree exactly on those.
    # It does go further than json for datetime/uuid/enum keys, which json
    # rejects and orjson stringifies; that direction only turns a
    # TypeError into a written file, never a differently-written one.
    _ORJSON_COMPAT = (
        orjson.OPT_PASSTHROUGH_DATETIME
        | orjson.OPT_PASSTHROUGH_DATACLASS
        | orjson.OPT_NON_STR_KEYS
    )


def _json_dumps(data: Any, kw: Dict[str, Any]) -> Union[str, bytes]:
    """Serialise `data`, via orjson when `kw` allows it, else json."""

    if HAS_ORJSON and not (kw.keys() - _ORJSON_DUMP_KEYS):
        indent = kw.get("indent")

        # ensure_ascii=True has no orjson equivalent, and OPT_INDENT_2 is
        # the only indentation it can produce.
        if not kw.get("ensure_ascii") and indent in (None, 2):
            option = _ORJSON_COMPAT

            if indent == 2:
                option |= orjson.OPT_INDENT_2
            if kw.get("sort_keys"):
                option |= orjson.OPT_SORT_KEYS

            return orjson.dumps(data, default=kw.get("default"), option=option)

    return json.dumps(data, **kw)


def _json_loads(content: Union[str, bytes], kw: Dict[str, Any]) -> Any:
    """Parse `content`, via orjson when `kw` is empty, else json.

    Any kwarg at all (object_hook, parse_float, cls, ...) means json --
    orjson supports none of them.
    """

    if HAS_ORJSON and not kw:
        return orjson.loads(content)

    return json.loads(content, **kw)


# Types read_pickle reconstructs without being asked. Every one of them is
# inert data: constructing it runs no user code and reaches nothing outside
# itself. What is deliberately absent matters more than what is here --
# builtins.eval/exec/getattr/__import__, os.system, subprocess.*, and every
# other callable a crafted pickle would name to get code running.
_SAFE_PICKLE_CLASSES: FrozenSet[Tuple[str, str]] = frozenset({
    ("builtins", name) for name in (
        "bool", "bytearray", "bytes", "complex", "dict", "float",
        "frozenset", "int", "list", "set", "slice", "str", "tuple",
        "range", "NoneType", "object",
    )
} | {
    ("collections", name) for name in (
        "OrderedDict", "defaultdict", "deque", "Counter", "namedtuple",
    )
} | {
    ("datetime", name) for name in (
        "date", "time", "datetime", "timedelta", "timezone",
    )
} | {
    ("decimal", "Decimal"), ("fractions", "Fraction"), ("uuid", "UUID"),
    ("pathlib", "PurePath"), ("pathlib", "PurePosixPath"),
    ("pathlib", "PureWindowsPath"), ("pathlib", "Path"),
    ("pathlib", "PosixPath"), ("pathlib", "WindowsPath"),
})


# What PickleSafety.BLOCKLIST refuses. Modules whose whole surface is a
# way to reach the OS, the interpreter, or raw memory, plus the individual
# builtins that evaluate or import. This is the one tier defined by what it
# denies rather than what it allows, so it is inherently best-effort -- an
# import path nobody thought of is not on the list.
_UNSAFE_PICKLE_MODULES: FrozenSet[str] = frozenset({
    "os", "nt", "posix", "subprocess", "sys", "shutil", "socket",
    "ctypes", "importlib", "multiprocessing", "pty", "runpy", "code",
    "codeop", "timeit", "webbrowser", "platform", "marshal", "pickle",
    "signal", "atexit", "gc", "gettext", "gzip", "bdb", "pdb",
})

_UNSAFE_PICKLE_CLASSES: FrozenSet[Tuple[str, str]] = frozenset({
    ("builtins", name) for name in (
        "eval", "exec", "compile", "open", "__import__", "input",
        "getattr", "setattr", "delattr", "globals", "locals", "vars",
        "breakpoint", "memoryview", "staticmethod", "classmethod",
        "property", "super", "type", "help", "exit", "quit",
    )
} | {
    ("operator", "attrgetter"), ("operator", "methodcaller"),
    ("operator", "itemgetter"), ("functools", "reduce"),
})


def _normalise_global(module: str, name: str) -> Tuple[str, str]:
    """Map a Python 2 module/name pair to its Python 3 equivalent.

    Protocols 0-2 write the Python 2 names for compatibility -- a set is
    stored as `__builtin__.set`, not `builtins.set` -- and pickle.Unpickler
    translates them back through _compat_pickle when loading. The checks
    here have to see the same translated pair pickle will act on, or they
    are checking a different name than the one that gets imported.

    Skipping this is not merely a false refusal of a legitimate old
    pickle. It is a hole: `__builtin__.eval` matches neither the allowed
    set nor the blocklist entry for `builtins.eval`, so at BLOCKLIST level
    it would sail straight through.
    """

    key = (module, name)

    if key in _compat_pickle.NAME_MAPPING:
        return _compat_pickle.NAME_MAPPING[key]

    if module in _compat_pickle.IMPORT_MAPPING:
        return _compat_pickle.IMPORT_MAPPING[module], name

    return key


class _RestrictedUnpickler(pickle.Unpickler):
    """Unpickler that only reconstructs what its PickleSafety level permits.

    find_class() is the single door every GLOBAL/STACK_GLOBAL opcode goes
    through -- refusing there is what stops a pickle from naming
    `os.system` (or anything else) and having it called during load.

    PickleSafety.NONE never reaches here; read_pickle uses plain pickle for
    it rather than constructing this at all.
    """

    def __init__(
        self,
        file: Any,
        level: PickleSafety,
        allowed: FrozenSet[Tuple[str, str]],
        allowed_modules: FrozenSet[str],
        **kw
    ) -> None:

        super().__init__(file, **kw)

        self._level = level
        self._allowed = allowed
        self._allowed_modules = allowed_modules

    def _permits(self, module: str, name: str) -> bool:
        # Decide on the pair pickle will actually import, not the one written
        # in the file -- see _normalise_global.
        module, name = _normalise_global(module, name)

        # Named explicitly via allow_classes, or one of the inert defaults --
        # true at every level, so allow_classes keeps working as an escape
        # hatch even at STRICT.
        if (module, name) in self._allowed:
            return True

        if self._level >= PickleSafety.STRICT:
            return False

        if self._level >= PickleSafety.MODULES:
            return module in self._allowed_modules

        # BLOCKLIST: anything that is not a known execution vector.
        return (
            module not in _UNSAFE_PICKLE_MODULES
            and (module, name) not in _UNSAFE_PICKLE_CLASSES
        )

    def find_class(self, module: str, name: str) -> Any:
        if self._permits(module, name):
            return super().find_class(module, name)

        raise pickle.UnpicklingError(
            f"read_pickle: refusing to load '{module}.{name}' at safety level "
            f"{self._level.name} -- pass allow_classes=[{name}] if this file "
            f"is yours and the class is safe to construct, or lower `safe` "
            f"(see PickleSafety) for a file you fully control."
        )
