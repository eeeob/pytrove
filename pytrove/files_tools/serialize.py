"""Reading and writing JSON and pickle files."""

from __future__ import annotations as _annotations

import io
import pickle
from collections.abc import Iterator
from typing import Any, cast

try:
    import jsonref
except ImportError:
    pass

from .._internal._optional import _optional_import
from .._internal._sentinel import _is_given
from ..enums import PickleSafety
from ..iter_tools import iter_flat_cont
from ..typings import JsonValue, LockProtocol, NestedContainer, PathLike, _T
from ._internal import _json_dumps, _json_loads
from ._pickling import _RestrictedUnpickler, _SAFE_PICKLE_CLASSES
from .paths import resolve_path
from .read import read_file
from .write import write_file


def read_json(path: PathLike, default: _T | type[object] = object, lock: LockProtocol | None = None, **kw: Any) -> JsonValue | _T:
    """Parse a JSON file, through orjson with the `fastjson` extra and no keywords.

    Args:
        path: The file to read.
        default: Returned when the file is missing; `{}` when omitted.
        lock: Held while reading.
        **kw: `json.loads` arguments; any of them means plain `json`.

    Returns:
        The parsed value, or the default.
    """
    try:
        content = read_file(path, binary=True, lock=lock)
    except FileNotFoundError:
        return default if _is_given(default) else {}

    return _json_loads(content, kw)


def write_json(path: PathLike, data: JsonValue, lock: LockProtocol | None = None, fsync: bool = True, **kw: Any) -> None:
    """Serialise `data` as JSON and write it atomically.

    No indent unless asked (`indent=2` stays on the orjson fast path).
    `ensure_ascii` defaults to `False`. Do not let another thread mutate
    `data` meanwhile: a list changed mid-walk is written as a mix of states.
    `lock` guards only the file, not the data.

    Args:
        path: The file to write.
        data: The value to serialise.
        lock: Held while writing.
        fsync: Whether the write must survive a power loss.
        **kw: `json.dumps` arguments.
    """
    kw.setdefault("ensure_ascii", False)
    content = _json_dumps(data, kw)
    del data
    write_file(path, content, encoding="utf-8", lock=lock, fsync=fsync)


def read_pickle(
    path: PathLike,
    default: _T | type[object] = object,
    lock: LockProtocol | None = None,
    *,
    allow_classes: NestedContainer[type] | None = None,
    allow_modules: NestedContainer[str] | None = None,
    safe: PickleSafety | bool = PickleSafety.STRICT,
    **kw: Any,
) -> Any | _T:
    """Unpickle a file, rebuilding only what `safe` allows.

    Unpickling runs whatever the data names; `STRICT` (the default) refuses all
    but inert types and `allow_classes`. Use a lower level only for files only
    you can write. `True`/`False` mean `STRICT`/`NONE`.

    Args:
        path: The file to read.
        default: Returned when the file is missing; `{}` when omitted.
        lock: Held while reading.
        allow_classes: Classes to allow at every level, matched by module and qualname.
        allow_modules: Modules whose contents `PickleSafety.MODULES` allows.
        safe: The safety level.
        **kw: `pickle.Unpickler` arguments.

    Returns:
        The object, or the default.

    Raises:
        pickle.UnpicklingError: If the data names something the level refuses.
    """
    try:
        content = read_file(path, binary=True, lock=lock)
    except FileNotFoundError:
        return default if _is_given(default) else {}

    if isinstance(safe, bool):  # `bool` is an `int`, so `True` would otherwise mean `BLOCKLIST`.
        safe = PickleSafety.STRICT if safe else PickleSafety.NONE

    if safe <= PickleSafety.NONE:
        return pickle.loads(content, **kw)

    # `ty` cannot solve `_T` from `NestedContainer[_T]`: the alias's bare `_T` arm
    # matches containers too, so the leaf types are the parameters' contracts.
    classes = cast(Iterator[type], iter_flat_cont(allow_classes))
    modules = cast(Iterator[str], iter_flat_cont(allow_modules))
    allowed = _SAFE_PICKLE_CLASSES | frozenset((cls.__module__, cls.__qualname__) for cls in classes)
    return _RestrictedUnpickler(io.BytesIO(content), safe, allowed, frozenset(modules), **kw).load()


def write_pickle(path: PathLike, data: Any, lock: LockProtocol | None = None, fsync: bool = True, **kw: Any) -> None:
    """Pickle `data` and write it atomically.

    `protocol` defaults to `pickle.HIGHEST_PROTOCOL`, readable only by a
    Python at least as new. The whole object is pickled to bytes first, which
    keeps the walk inside the C pickler so other threads cannot interleave.

    Args:
        path: The file to write.
        data: The object.
        lock: Held while writing.
        fsync: Whether the write must survive a power loss.
        **kw: `pickle.dumps` arguments.
    """
    kw.setdefault("protocol", pickle.HIGHEST_PROTOCOL)
    content = pickle.dumps(data, **kw)
    del data
    write_file(path, content, lock=lock, fsync=fsync)


@_optional_import(("jsonref", "jsonref"))
def load_ref_json(
    path: PathLike, default: _T | type[object] = object, lock: LockProtocol | None = None, **kw: Any,
) -> JsonValue | _T:
    """Load a JSON file and resolve every `$ref`, relative ones against the file's directory.

    Args:
        path: The file to read.
        default: Returned when the file is missing; `{}` when omitted.
        lock: Held while reading.
        **kw: `jsonref.loads` arguments; `proxies` and `lazy_load` default to `False`.

    Returns:
        The resolved document, or the default.
    """
    path = resolve_path(path)
    kw.setdefault("proxies", False)
    kw.setdefault("lazy_load", False)
    kw.setdefault("base_uri", path.as_uri())

    try:
        return jsonref.loads(read_file(path, encoding="utf-8", lock=lock), **kw)
    except FileNotFoundError:
        return default if _is_given(default) else {}


load_json = read_json
save_json = write_json

__all__ = (
    "read_json",
    "write_json",
    "load_json",
    "save_json",
    "read_pickle",
    "write_pickle",
    "load_ref_json",
)
