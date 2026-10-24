"""`files_tools._internal.pickling`: the restricted unpickler and its tables."""

from __future__ import annotations as _annotations

import io
import pickle
from pathlib import Path, PurePosixPath

import pytest

from pytrove.enums import PickleSafety
from pytrove.files_tools._internal import (
    _RestrictedUnpickler,
    _normalise_global,
    _SAFE_PICKLE_CLASSES,
    _UNSAFE_PICKLE_CLASSES,
    _UNSAFE_PICKLE_MODULES,
)


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
    assert "allow_classes=[system]" in str(caught.value)


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
