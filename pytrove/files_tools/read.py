"""Reading a file whole, as text or bytes."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, Any, Literal, overload

if TYPE_CHECKING:
    from ..typings import LockProtocol, PathLike


# The `binary=True` overload comes first: one without `binary` but with `**kw` would absorb it and match.
@overload
def read_file(path: PathLike, *, binary: Literal[True], lock: LockProtocol | None = None, **kw: Any) -> bytes: ...
@overload
def read_file(
    path: PathLike, *, binary: Literal[False] = False, encoding: str = "utf-8", lock: LockProtocol | None = None,
    **kw: Any,
) -> str: ...
def read_file(
    path: PathLike,
    *,
    binary: bool = False,
    encoding: str = "utf-8",
    lock: LockProtocol | None = None,
    **kw: Any,
) -> str | bytes:
    """Read a whole file, as text or bytes.

    `path` is opened as given, not resolved, since resolving costs about as much as the read.

    Args:
        path: The file to read.
        binary: Whether to return bytes.
        encoding: The text encoding.
        lock: Held while reading.
        **kw: Extra `open` arguments.

    Returns:
        The contents.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    try:
        if lock is not None:
            lock.acquire()

        if binary:
            with open(path, "rb", **kw) as f:
                return f.read()

        with open(path, encoding=encoding, **kw) as f:
            return f.read()
    finally:
        if lock is not None:
            lock.release()


__all__ = ("read_file",)
