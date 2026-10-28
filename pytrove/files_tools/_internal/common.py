"""Helpers private to `files_tools`: tree removal and spill parts."""

from __future__ import annotations as _annotations

import logging
import math
import os
import shutil
import sys
from functools import partial
from typing import TYPE_CHECKING, Any, Final, Literal, TypedDict, cast

from ..._internal import _is_link, _COPY_BUF
from ...enums import TruncateSide
from ...iter_tools import dedupe, iter_flat_cont
from ..paths import ensure_dir, ensure_path, resolve_path

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from ...typings import NestedContainer, PathLike

_SPILL_PARTS: Final[int] = 10
"""The most parts one `truncate_file` call spills into; a part grows past `size` to stay within it."""

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
        int(suffix)
        for name in names
        if name.startswith(prefix)
        # ASCII only: `str.isdigit` also takes `²`, which `int` refuses.
        and (suffix := name[len(prefix) :]).isascii()
        and suffix.isdigit()
    ]
    return max(numbers, default=0) + 1


def _on_exc_remove_folders(
    func: Callable[..., Any], path: str, exc: BaseException, *, base_path: str
) -> None:
    """Handle an `rmtree` error: unlink links, ignore vanished children, raise the rest.

    `rmtree` refuses a link it is handed or a Windows junction it finds
    (`os.path.islink`), and fails to open a root link that dangles
    (`os.open`, `FileNotFoundError`); unlinking the link itself removes it
    without touching what it points at.

    Args:
        func: The function that failed.
        path: The path it failed on.
        exc: The exception.
        base_path: The tree's root, whose own absence is not ignored.

    Raises:
        BaseException: `exc`, when it is neither case above.
    """
    if (func == os.path.islink or str(path) == base_path) and _is_link(path):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        return

    if isinstance(exc, FileNotFoundError) and str(path) != base_path:
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
            exc.filename = str(path)

            if not return_exc:
                raise exc

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
        size: Bytes that stay, and the part size unless that makes more than `_SPILL_PARTS` parts.
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
    # Rounded up, or a tiny spill would write no part.
    part_size = max(size, math.ceil(dropped / _SPILL_PARTS))
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
    "_next_part",
    "_on_exc_remove_folders",
    "_remove",
    "_rmtree",
    "_spill_parts",
    "_SPILL_PARTS",
)
