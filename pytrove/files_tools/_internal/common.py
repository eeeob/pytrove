"""Helpers private to `files_tools`: JSON codecs, tree removal and spill parts."""

from __future__ import annotations as _annotations

import json
import logging
import math
import os
import shutil
import sys
from functools import partial
from typing import TYPE_CHECKING, Any, Final, Literal, TypedDict, cast

try:
    import orjson  # type: ignore[import-not-found]  # Optional: the `json` extra.
except ImportError:
    HAS_ORJSON = False
else:
    HAS_ORJSON = True

from ..._internal import _is_link, _COPY_BUF
from ...callable_tools import safe_call
from ...enums import TruncateSide
from ...iter_tools import dedupe, iter_flat_cont
from ..paths import ensure_dir, ensure_path, resolve_path

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from ...typings import NestedContainer, PathLike

_SPILL_PARTS: Final[int] = 10
"""How many parts `truncate_file` spills into when `size` is 0 and names no part length."""

_ORJSON_DUMP_KEYS: Final[frozenset[str]] = frozenset(
    {"ensure_ascii", "indent", "sort_keys", "default"}
)
"""The `write_json` keywords orjson can honour; any other keyword means plain `json`.

orjson only indents by 2, never escapes to ASCII, and writes compact JSON
without spaces, so a byte-for-byte comparison should pin `indent`.
"""

# Hands datetimes and dataclasses back to `default` (or a `TypeError`), as `json` does, and accepts the
# int/float/bool/None keys `json` stringifies, so installing the extra never changes what is written.
_ORJSON_COMPAT: Final[int] = (
    orjson.OPT_PASSTHROUGH_DATETIME | orjson.OPT_PASSTHROUGH_DATACLASS | orjson.OPT_NON_STR_KEYS
    if HAS_ORJSON
    else 0
)
"""The orjson options that make its output match `json`'s."""

log = logging.getLogger(__name__)


class _MkdirOptions(TypedDict, total=False):
    """What `Path.mkdir` takes, so `ensure_dir` can type its `**kwargs` key by key."""

    mode: int
    """Permissions for the last component only, masked by the umask; ignored on Windows."""

    parents: bool
    """Whether to create missing parents."""

    exist_ok: bool
    """Whether an existing directory is fine; an existing file still raises."""


def _next_part(folder: Path, stem: str) -> int:
    """Find the first free number for a `<stem>.N` part file in `folder`.

    One past the highest existing part, so a second truncation adds parts
    instead of overwriting the first set. Only an all-digit suffix counts,
    so `app.log.bak` is ignored.

    Args:
        folder: The directory holding the parts.
        stem: The file name the parts are numbered after.

    Returns:
        The next part number, starting at 1.
    """
    prefix = f"{stem}."

    try:
        names = os.listdir(folder)
    except OSError:
        return 1

    numbers = [
        int(name[len(prefix) :])
        for name in names
        if name.startswith(prefix) and name[len(prefix) :].isdigit()
    ]
    return max(numbers, default=0) + 1


def _json_dumps(data: Any, kw: dict[str, Any]) -> str | bytes:
    """Serialise `data`, through orjson when every keyword allows it, else `json`.

    Args:
        data: The value to serialise.
        kw: `json.dumps` keyword arguments.

    Returns:
        The JSON text, or bytes from orjson.
    """
    if HAS_ORJSON and not (kw.keys() - _ORJSON_DUMP_KEYS):
        indent = kw.get("indent")

        if not kw.get("ensure_ascii") and indent in (None, 2):
            option = _ORJSON_COMPAT

            if indent == 2:
                option |= orjson.OPT_INDENT_2

            if kw.get("sort_keys"):
                option |= orjson.OPT_SORT_KEYS

            return orjson.dumps(data, default=kw.get("default"), option=option)

    return json.dumps(data, **kw)


def _json_loads(content: str | bytes, kw: dict[str, Any]) -> Any:
    """Parse JSON, through orjson when no keyword is given, else `json`.

    Args:
        content: The JSON text or bytes.
        kw: `json.loads` keyword arguments; orjson supports none of them.

    Returns:
        The parsed value.
    """
    if HAS_ORJSON and not kw:
        return orjson.loads(content)

    return json.loads(content, **kw)


def _on_exc_remove_folders(
    func: Callable[..., Any], path: str, exc: BaseException, *, base_path: str
) -> None:
    """Handle an `rmtree` error: ignore vanished children, unlink junctions, raise the rest.

    `rmtree` refuses to walk into a Windows junction; unlinking the link
    itself removes it without touching what it points at.

    Args:
        func: The function that failed.
        path: The path it failed on.
        exc: The exception.
        base_path: The tree's root, whose own absence is not ignored.

    Raises:
        BaseException: `exc`, when it is neither case above.
    """
    if isinstance(exc, FileNotFoundError) and str(path) != base_path:
        return

    if func == os.path.islink and _is_link(path):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        return

    raise exc


def _rmtree(folder: Path) -> None:
    """Remove a directory tree, tolerating junctions and children that vanish meanwhile.

    Args:
        folder: The real directory to remove.
    """
    handler = partial(_on_exc_remove_folders, base_path=str(folder))

    if sys.version_info >= (3, 12):
        shutil.rmtree(folder, onexc=handler)
    else:
        shutil.rmtree(folder, onerror=lambda func, path, exc_info: handler(func, path, exc_info[1]))


def _remove(
    paths: tuple[NestedContainer[PathLike], ...],
    remover: Callable[[Path], object],
    who: str,
    return_exc: bool,
    log_exc: bool,
) -> list[Path | OSError]:
    """Apply one remover to each path, with the removers' shared contract.

    Args:
        paths: The paths, at any nesting.
        remover: Removes one path.
        who: The public name, for log messages.
        return_exc: Whether to collect failures and carry on.
        log_exc: Whether to log each collected failure.

    Returns:
        What was removed, with collected failures in place.

    Raises:
        OSError: The first failure, unless `return_exc` is set.
    """
    removed: list[Path | OSError] = []

    # `ty` binds `_T` to the container arm of the recursive `NestedContainer[_T]`, so
    # it cannot recover the leaf type (astral-sh/ty#1703); the parameter states it.
    leaves = cast("Iterator[PathLike]", iter_flat_cont(paths))

    for path in dedupe(map(ensure_path, leaves)):
        try:
            remover(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            safe_call(setattr, exc, "filename", str(path), include_exc=AttributeError)

            if not return_exc:
                raise

            if log_exc:
                log.error("%s: could not remove %s", who, str(path), exc_info=exc)

            removed.append(exc)
        else:
            removed.append(path)

    return removed


def _spill_parts(
    path: Path,
    side: TruncateSide,
    size: int,
    dropped: int,
    spill: Literal[True] | PathLike,
    fsync: bool,
) -> list[Path]:
    """Copy the bytes `truncate_file` will remove into numbered part files.

    Args:
        path: The file being trimmed; only read here.
        side: Which end is removed.
        size: Bytes that stay, and the part size unless 0.
        dropped: Bytes that go.
        spill: `True` for the file's own directory, or the directory to use.
        fsync: Whether to flush each part.

    Returns:
        The parts written, in order.
    """
    # `remove` and `write` import this module.
    from ..remove import remove_file  # noqa: PLC0415 - see above
    from ..write import atomic_write  # noqa: PLC0415 - see above

    folder = ensure_dir(path.parent if spill is True else resolve_path(spill))
    part_size = size or math.ceil(
        dropped / _SPILL_PARTS
    )  # Rounded up, or a tiny spill would write no part.
    number = _next_part(folder, path.name)
    left = dropped
    parts: list[Path] = []

    with open(path, "rb") as src:
        src.seek(0 if side == TruncateSide.HEAD else size)

        while left > 0:
            want = min(part_size, left)
            part = folder / f"{path.name}.{number}"
            written = 0

            with atomic_write(part, binary=True, fsync=fsync) as out:
                while written < want and (chunk := src.read(min(_COPY_BUF, want - written))):
                    out.write(chunk)
                    written += len(chunk)

            if not written:  # The file shrank under us; an empty part would misreport it.
                remove_file(part)
                break

            parts.append(part)
            number += 1
            left -= written

            if written < want:
                break

    return parts


__all__ = (
    "_MkdirOptions",
    "_json_dumps",
    "_json_loads",
    "_next_part",
    "_on_exc_remove_folders",
    "_remove",
    "_rmtree",
    "_spill_parts",
    "_ORJSON_COMPAT",
    "_ORJSON_DUMP_KEYS",
    "_SPILL_PARTS",
    "HAS_ORJSON",
)
