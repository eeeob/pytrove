"""`files_tools._internal.pickling`: the restricted unpickler and its tables."""

from __future__ import annotations as _annotations

import collections
import collections.abc
import functools
import io
import json
import operator
import os
import pickle
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import pytest

from pytrove.enums import PickleSafety
from pytrove.files_tools._internal import (
    _RestrictedUnpickler,
    _blocked_callable_ids,
    _defining_module,
    _is_blocked_object,
    _normalise_global,
    _SAFE_PICKLE_CLASSES,
    _UNSAFE_PICKLE_CLASSES,
    _UNSAFE_PICKLE_MODULES,
)


class Custom:
    """A plain class, pickled at every protocol."""

    def __init__(self, value: int) -> None:
        """Store `value`."""
        self.value = value

    class Inner:
        """A nested class: its global is the dotted `Custom.Inner`."""


def _stack_global(module: str, name: str) -> bytes:
    """Build a protocol-4 pickle that looks up `module` + `name` and calls it with no arguments."""
    parts = b"".join(b"\x8c" + bytes([len(s)]) + s for s in (module.encode(), name.encode()))
    return b"\x80\x04" + parts + b"\x93)R."  # STACK_GLOBAL, EMPTY_TUPLE, REDUCE


def _load(
    data: bytes,
    level: PickleSafety,
    allowed: frozenset[tuple[str, str]] = frozenset(),
    modules: frozenset[str] = frozenset(),
) -> object:
    """Unpickle `data` at `level`."""
    return _RestrictedUnpickler(io.BytesIO(data), level, allowed, modules).load()


def test_safe_and_unsafe_tables() -> None:
    assert ("builtins", "dict") in _SAFE_PICKLE_CLASSES
    assert ("pathlib", "Path") in _SAFE_PICKLE_CLASSES
    assert ("_codecs", "encode") in _SAFE_PICKLE_CLASSES
    assert ("copyreg", "_reconstructor") in _SAFE_PICKLE_CLASSES
    # The factory builds no data of its own: a namedtuple pickles under its own class.
    assert ("collections", "namedtuple") not in _SAFE_PICKLE_CLASSES
    assert ("builtins", "eval") in _UNSAFE_PICKLE_CLASSES
    assert ("functools", "reduce") in _UNSAFE_PICKLE_CLASSES
    assert "os" in _UNSAFE_PICKLE_MODULES
    assert not _SAFE_PICKLE_CLASSES & _UNSAFE_PICKLE_CLASSES
    assert not {module for module, _ in _SAFE_PICKLE_CLASSES} & _UNSAFE_PICKLE_MODULES


def test_normalise_global_maps_python_2_names() -> None:
    assert _normalise_global("__builtin__", "xrange") == (
        "builtins",
        "range",
    )  # a `NAME_MAPPING` pair
    assert _normalise_global("__builtin__", "eval") == (
        "builtins",
        "eval",
    )  # an `IMPORT_MAPPING` module
    assert _normalise_global("copy_reg", "x") == ("copyreg", "x")
    assert _normalise_global("mine", "Thing") == ("mine", "Thing")


def test_normalise_global_maps_the_3_13_pathlib_module() -> None:
    # 3.13 defines the path classes in `pathlib._local` and pickles them under it.
    assert _normalise_global("pathlib._local", "PosixPath") == ("pathlib", "PosixPath")
    assert _normalise_global("pathlib._local", "WindowsPath") == ("pathlib", "WindowsPath")


def test_a_3_13_path_pickle_loads_on_every_version() -> None:
    # What 3.13 writes for `PurePosixPath("p")`, so this runs the same on every interpreter.
    data = b"cpathlib._local\nPurePosixPath\n(Vp\ntR."

    assert _load(data, PickleSafety.STRICT, _SAFE_PICKLE_CLASSES) == PurePosixPath("p")

    with pytest.raises(pickle.UnpicklingError, match="pathlib.PurePosixPath"):
        _load(data, PickleSafety.STRICT)


def test_restricted_unpickler_levels() -> None:
    data = pickle.dumps(Path("p"))

    assert _load(data, PickleSafety.STRICT, _SAFE_PICKLE_CLASSES) == Path("p")

    with pytest.raises(pickle.UnpicklingError, match="STRICT"):
        _load(data, PickleSafety.STRICT)

    assert _load(
        data, PickleSafety.MODULES, modules=frozenset({"pathlib", "pathlib._local"})
    ) == Path("p")

    with pytest.raises(pickle.UnpicklingError, match="MODULES"):
        _load(data, PickleSafety.MODULES, modules=frozenset({"other"}))

    assert _load(data, PickleSafety.BLOCKLIST) == Path("p")


def test_blocklist_refuses_modules_and_callables_even_under_python_2_names() -> None:
    for payload in (pickle.dumps(eval, protocol=2), b"c__builtin__\neval\n.", b"cos\nsystem\n."):
        with pytest.raises(pickle.UnpicklingError, match="refusing to load"):
            _load(payload, PickleSafety.BLOCKLIST)

    assert (
        _load(b"c__builtin__\neval\n.", PickleSafety.BLOCKLIST, frozenset({("builtins", "eval")}))
        is eval
    )


def test_the_refusal_names_the_global_and_the_cure() -> None:
    with pytest.raises(pickle.UnpicklingError) as caught:
        _load(b"cos\nsystem\n.", PickleSafety.STRICT)

    assert "'os.system'" in str(caught.value)
    # `allow_classes` takes classes, so the message cannot offer it a function as if it were one.
    assert "if this file is yours and 'system' is a class" in str(caught.value)
    assert "`allow_classes`" in str(caught.value)
    assert "allow_classes=[" not in str(caught.value)


def test_unpickler_keywords_reach_the_base_class() -> None:
    buffers: list[pickle.PickleBuffer] = []
    data = pickle.dumps(
        {"k": pickle.PickleBuffer(bytearray(b"v"))}, protocol=5, buffer_callback=buffers.append
    )
    unpickler = _RestrictedUnpickler(
        io.BytesIO(data),
        PickleSafety.STRICT,
        _SAFE_PICKLE_CLASSES,
        frozenset(),
        buffers=[b.raw() for b in buffers],
    )

    assert unpickler.load() == {"k": bytearray(b"v")}


# --- dotted names and the module a global comes from -----------------------


@pytest.mark.parametrize(
    ("level", "modules"),
    [
        (PickleSafety.BLOCKLIST, frozenset()),
        (PickleSafety.MODULES, frozenset({"pathlib", "pathlib._local"})),
        (PickleSafety.STRICT, frozenset()),
    ],
)
@pytest.mark.parametrize(
    "name",
    [
        "os.getcwd",  # `pathlib.os` is the `os` module, refused whole at BLOCKLIST
        "os.system",
        "PurePath.__module__",  # a str, which names no module
    ],
)
def test_a_dotted_name_cannot_reach_through_an_allowed_module(
    level: PickleSafety, modules: frozenset[str], name: str
) -> None:
    # From protocol 4 `find_class` walks a dotted name attribute by attribute.
    with pytest.raises(pickle.UnpicklingError, match=f"'pathlib.{name}'"):
        _load(_stack_global("pathlib", name), level, _SAFE_PICKLE_CLASSES, modules)


def test_a_dotted_name_cannot_reach_a_builtin_method() -> None:
    # `builtins.__dict__.get` would hand back `eval` to a second REDUCE.
    with pytest.raises(pickle.UnpicklingError, match="'builtins.__dict__.copy'"):
        _load(_stack_global("builtins", "__dict__.copy"), PickleSafety.BLOCKLIST)


@pytest.mark.parametrize(
    ("module", "name"),
    [
        ("pathlib", "os"),  # the `os` module, refused whole
        ("tempfile", "_os"),
        ("io", "open"),  # `builtins.open`, whose `__module__` is `io`
        ("os.path", "os"),  # a module string that is not itself in the table
    ],
)
def test_blocklist_judges_the_object_a_plain_name_reaches(module: str, name: str) -> None:
    # A bare GLOBAL lookup, not called, so only the lookup itself is refused.
    data = b"\x80\x04" + b"".join(b"\x8c" + bytes([len(s)]) + s.encode() for s in (module, name))

    with pytest.raises(pickle.UnpicklingError, match=f"'{module}.{name}'"):
        _load(data + b"\x93.", PickleSafety.BLOCKLIST)


def test_is_blocked_object() -> None:
    assert _is_blocked_object(os)
    assert _is_blocked_object(os.system)  # defined in `nt` or `posix`
    assert _is_blocked_object(io.open)
    assert _is_blocked_object(operator.attrgetter)
    assert not _is_blocked_object(io.BytesIO)
    assert not _is_blocked_object(json)
    assert not _is_blocked_object({})


def test_blocked_callable_ids_resolve_every_present_callable() -> None:
    assert id(eval) in _blocked_callable_ids()
    assert id(functools.reduce) in _blocked_callable_ids()
    assert id(dict) not in _blocked_callable_ids()


def test_a_dotted_name_defined_in_its_module_still_loads() -> None:
    data = pickle.dumps(Custom.Inner(), protocol=4)
    module = Custom.__module__

    assert type(_load(data, PickleSafety.BLOCKLIST)) is Custom.Inner
    assert type(_load(data, PickleSafety.MODULES, modules=frozenset({module}))) is Custom.Inner
    allowed = frozenset({(module, "Custom.Inner")})
    assert type(_load(data, PickleSafety.STRICT, allowed)) is Custom.Inner

    with pytest.raises(pickle.UnpicklingError):
        _load(data, PickleSafety.STRICT)


def test_modules_refuses_a_name_a_module_only_imports() -> None:
    # `json` imports `JSONDecoder` from `json.decoder`, where it is defined.
    imported = b"\x80\x04\x8c\x04json\x8c\x0bJSONDecoder\x93."

    with pytest.raises(pickle.UnpicklingError, match="'json.JSONDecoder'"):
        _load(imported, PickleSafety.MODULES, modules=frozenset({"json"}))

    own = pickle.dumps(json.JSONDecoder)
    assert _load(own, PickleSafety.MODULES, modules=frozenset({"json.decoder"})) is json.JSONDecoder


def test_allow_modules_names_one_module_and_not_its_submodules() -> None:
    data = pickle.dumps(collections.abc.Sized)

    assert _load(data, PickleSafety.MODULES, modules=frozenset({"collections.abc"})) is (
        collections.abc.Sized
    )

    with pytest.raises(pickle.UnpicklingError, match="'collections.abc.Sized'"):
        _load(data, PickleSafety.MODULES, modules=frozenset({"collections"}))


def test_defining_module_reads_dunder_module_and_maps_private_ones() -> None:
    assert _defining_module(Custom) == Custom.__module__
    assert _defining_module(Path) == "pathlib"  # `pathlib._local` on 3.13
    assert _defining_module({}) is None
    assert _defining_module({}.copy) is None  # a bound builtin method's `__module__` is `None`


# --- old protocols at STRICT -----------------------------------------------


@pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
def test_strict_loads_inert_data_at_every_protocol(protocol: int) -> None:
    # Protocols 0-2 build `bytes` through `_codecs.encode`.
    data = {
        "bytes": b"\x00ab",
        "set": {1, 2},
        "when": datetime(2024, 1, 2, tzinfo=timezone.utc),
        "path": PurePosixPath("p"),
        "deque": collections.deque([1]),
    }

    assert (
        _load(pickle.dumps(data, protocol=protocol), PickleSafety.STRICT, _SAFE_PICKLE_CLASSES)
        == data
    )


@pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
def test_strict_loads_an_allowed_class_at_every_protocol(protocol: int) -> None:
    # Protocols 0-1 build it through `copyreg._reconstructor`.
    data = pickle.dumps(Custom(3), protocol=protocol)
    allowed = _SAFE_PICKLE_CLASSES | {(Custom.__module__, "Custom")}

    loaded = _load(data, PickleSafety.STRICT, allowed)
    assert isinstance(loaded, Custom)
    assert loaded.value == 3

    with pytest.raises(pickle.UnpicklingError, match="Custom"):
        _load(data, PickleSafety.STRICT, _SAFE_PICKLE_CLASSES)
