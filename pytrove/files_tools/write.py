"""Writing files atomically, and trimming them."""

from __future__ import annotations as _annotations

import os
import tempfile
from contextlib import contextmanager
from typing import IO, TYPE_CHECKING, Any, Literal, overload

from .._internal import _COPY_BUF
from ..callable_tools import safe_call
from ..enums import TruncateSide
from ..errors import ValidationError
from ._internal import _spill_parts
from .paths import resolve_path
from .remove import remove_files

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..typings import LockProtocol, PathLike, _False, _True


@contextmanager
def atomic_write(
    path: PathLike,
    binary: bool = False,
    encoding: str = "utf-8",
    mode: int | None = None,
    lock: LockProtocol | None = None,
    fsync: bool = True,
) -> Generator[IO[Any], None, None]:
    """Open a temp file that replaces `path` only when the block exits cleanly.

    A reader never sees a partial file, and a block that raises leaves the old
    contents untouched. A failed write removes the temp file.

    Args:
        path: The file to write.
        binary: Whether to open in binary mode.
        encoding: The text encoding.
        mode: Permission bits; the existing file's, or `0o644`, by default.
        lock: Held while writing and replacing.
        fsync: Whether to flush the data and the directory entry to disk.

    Yields:
        The writable temp file.
    """
    path = resolve_path(path)
    directory = path.parent

    if mode is None:
        try:
            mode = path.stat().st_mode & 0o777
        except FileNotFoundError:
            mode = 0o644

    # Acquired outside the `try`: a failed `acquire` must not reach a `release` that would
    # raise for an unheld lock and replace the original error.
    if lock is not None:
        lock.acquire()

    try:
        # `mkstemp` creates it `0o600`, so it stays private until the `chmod` below.
        fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
        replaced = False

        try:
            with os.fdopen(fd, "wb" if binary else "w", encoding=None if binary else encoding) as f:
                yield f

                if fsync:
                    f.flush()
                    os.fsync(f.fileno())

            os.chmod(tmp_path, mode)
            os.replace(tmp_path, path)
            replaced = True

            if fsync:
                # The rename lives in the directory, which needs its own `fsync` to survive a power loss.
                try:
                    dir_fd = os.open(directory, os.O_RDONLY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        safe_call(os.close, dir_fd)
                except OSError:
                    pass
        finally:
            if not replaced:
                remove_files(tmp_path, return_exc=True, log_exc=True)
    finally:
        if lock is not None:
            lock.release()


def write_file(
    path: PathLike,
    content: str | bytes,
    encoding: str = "utf-8",
    mode: int | None = None,
    lock: LockProtocol | None = None,
    fsync: bool = True,
) -> None:
    """Write `content` to `path`, replacing it atomically.

    Args:
        path: The file to write.
        content: Text, or bytes for a binary write.
        encoding: The text encoding.
        mode: Permission bits; the existing file's, or `0o644`, by default.
        lock: Held while writing and replacing.
        fsync: Whether to make the write survive a power loss, at most of the cost;
            the write stays atomic either way.
    """
    with atomic_write(
        path,
        binary=isinstance(content, bytes),
        encoding=encoding,
        mode=mode,
        lock=lock,
        fsync=fsync,
    ) as f:
        f.write(content)


@overload
def truncate_file(
    path: PathLike,
    size: int,
    cut: TruncateSide | Literal["head", "tail"] = TruncateSide.HEAD,
    spill: _False = False,
    fsync: bool = True,
) -> Path: ...
@overload
def truncate_file(
    path: PathLike,
    size: int,
    cut: TruncateSide | Literal["head", "tail"],
    spill: _True | PathLike,
    fsync: bool = True,
) -> list[Path]: ...
@overload
def truncate_file(
    path: PathLike,
    size: int,
    cut: TruncateSide | Literal["head", "tail"] = TruncateSide.HEAD,
    *,
    spill: _True | PathLike,
    fsync: bool = True,
) -> list[Path]: ...
@overload
def truncate_file(
    path: PathLike,
    size: int,
    cut: TruncateSide | Literal["head", "tail"] = TruncateSide.HEAD,
    spill: bool | PathLike = False,
    fsync: bool = True,
) -> Path | list[Path]: ...
def truncate_file(
    path: PathLike,
    size: int,
    cut: TruncateSide | Literal["head", "tail"] = TruncateSide.HEAD,
    spill: bool | PathLike = False,
    fsync: bool = True,
) -> Path | list[Path]:
    """Leave `size` bytes in a file, removing the rest from one end.

    `HEAD` keeps the last `size` bytes (as a log wants) by rewriting through a
    rename, so the inode changes; `TAIL` keeps the first `size` bytes in place.
    Spilled bytes go to `<file>.1`, `<file>.2`, ... in original order, numbered
    after any existing parts, and are written before the file is cut, so an
    interruption or a failed spill can duplicate bytes but never lose them.
    One call writes at most ten parts of `size` bytes each, longer ones when
    ten of that size would not hold the spill. Mode is preserved.

    Args:
        path: The file to trim.
        size: Bytes to leave; also the spill part size, within the ten-part cap.
        cut: Which end goes, as the enum or its string.
        spill: `False` to discard the removed bytes, `True` to write them beside
            the file, or a directory to write them into (`""` is the current one).
        fsync: Whether to flush everything written to disk.

    Returns:
        The file itself without `spill`; with it, the parts written, empty when nothing was cut.

    Raises:
        ValidationError: If `size` is not a non-negative int or `path` is not a file.
        ValueError: If `cut` is neither a `TruncateSide` nor one of its values.
        FileNotFoundError: If `path` does not exist.
        FileExistsError: If `spill` names a file rather than a directory; nothing is cut.
    """
    path = resolve_path(path, strict=True)
    side = TruncateSide(cut)

    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        msg = f"truncate_file: size must be a whole number of bytes, not {size!r}"
        raise ValidationError(msg)

    if not path.is_file():
        msg = f"truncate_file: {str(path)!r} is not a file"
        raise ValidationError(msg)

    total = path.stat().st_size

    if total <= size:
        return path if spill is False else []

    dropped = total - size
    # `is False`, not truthiness: `""` names a directory too.
    parts = [] if spill is False else _spill_parts(path, side, size, dropped, spill, fsync)

    if side == TruncateSide.TAIL:
        with open(path, "r+b") as f:
            f.truncate(size)

            if fsync:
                os.fsync(f.fileno())
    else:
        # The reader sits inside `atomic_write`, because Windows refuses to rename over an open file.
        with atomic_write(path, binary=True, fsync=fsync) as out, open(path, "rb") as src:
            src.seek(dropped)

            while chunk := src.read(_COPY_BUF):
                out.write(chunk)

    return path if spill is False else parts


__all__ = (
    "atomic_write",
    "write_file",
    "truncate_file",
)
