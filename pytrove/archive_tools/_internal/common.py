"""Constants and small helpers shared by both directions of `archive_tools`."""

from __future__ import annotations as _annotations

import os
import stat
import sys
from concurrent.futures import Executor
from typing import TYPE_CHECKING, Any, Final, TypeAlias

from ..._internal import _build_error_msg, _unmet, _HAS_FILE_ATTRIBUTES
from ...enums import ArchiveFormat
from ...errors import ValidationError
from . import backends

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

_LINK_MAX: Final[int] = 4096
"""The longest link destination read from a zip member; no platform stores a longer path."""

_NT: Final[bool] = os.name == "nt"
"""Whether paths follow Windows rules, which strip trailing dots and spaces."""

_SUFFIXES: Final[tuple[tuple[str, ArchiveFormat], ...]] = (
    (".zip", ArchiveFormat.ZIP),
    (".tar.zst", ArchiveFormat.TAR_ZST),
    (".tar.gz", ArchiveFormat.TAR_GZ),
    (".tgz", ArchiveFormat.TAR_GZ),
)
"""File-name endings and the format each names."""

_WalkEntry: TypeAlias = tuple[str, str, bool]
"""What the folder walk yields: absolute path, posix archive name, whether it is a directory."""


def _format_from_suffix(name: str) -> ArchiveFormat | None:
    """Read the format a file name claims.

    Args:
        name: The file name, in any case.

    Returns:
        The format its ending names, or `None` for an unknown ending.
    """
    lower = name.lower()

    for suffix, fmt in _SUFFIXES:
        if lower.endswith(suffix):
            return fmt

    return None


def _split_workers(workers: int | Executor | None, who: str) -> tuple[int | None, Executor | None]:
    """Read the `workers` argument as a thread count or a pool.

    Args:
        workers: A pool; a count, `-1` for one per core; or `None`/`0` for the calling thread.
        who: The public function's name, for the error message.

    Returns:
        The count and the pool; at most one is set.

    Raises:
        ValidationError: For anything else, `bool` included.
    """
    if workers is None or isinstance(workers, Executor):
        return None, workers

    if isinstance(workers, int) and not isinstance(workers, bool):
        return ((os.cpu_count() or 1) if workers < 0 else workers), None

    msg = f"{who}: workers takes a count or an executor, not {type(workers).__name__}"
    raise ValidationError(msg)


def _new_prefixes(path: str, seen: set[str]) -> list[str]:
    """Record the prefixes of a posix path that `seen` lacks, `a` before `a/b` before `path`.

    `seen` only ever gains a path together with its prefixes, so the walk up
    stops at the first one already there; a path whose parent is known costs
    one lookup, not one join per level.

    Args:
        path: A relative posix path; empty for the root, which has no prefix.
        seen: The prefixes recorded so far; the new ones are added to it.

    Returns:
        The prefixes just added, outermost first.

    Example:
        >>> seen = {"a"}
        >>> _new_prefixes("a/b/c", seen)
        ['a/b', 'a/b/c']
        >>> _new_prefixes("a/b", seen)
        []
    """
    new = []

    while path and path not in seen:
        new.append(path)
        path = path.rpartition("/")[0]

    new.reverse()
    seen.update(new)
    return new


def _nt_strip(name: str) -> str:
    """Spell a posix name as Windows stores it: each segment without trailing dots and spaces.

    A segment left empty is dropped, as the filesystem drops it.

    Args:
        name: A posix member name.

    Returns:
        The name Windows would write.

    Example:
        >>> _nt_strip("a. /. /b..")
        'a/b'
    """
    return "/".join(part for raw in name.split("/") if (part := raw.rstrip(". ")))


def _is_hidden(rel: str, entry: os.DirEntry | None) -> bool:
    """Tell whether a walked entry is hidden: a leading dot, or the Windows hidden attribute.

    It is an exclude rule, so it takes a rule's two arguments.

    Args:
        rel: The relative path, unused.
        entry: The directory entry.

    Returns:
        Whether the entry is hidden; `False` when it cannot be read.
    """
    del rel  # A rule receives it; only the entry decides here.

    if entry is None:
        return False

    if entry.name.startswith("."):
        return True

    if not _HAS_FILE_ATTRIBUTES:
        return False

    try:
        # Windows-only field, guarded by `_HAS_FILE_ATTRIBUTES` at runtime; `ty`
        # cannot narrow on that flag (the tests patch it) and reports it on Linux.
        return bool(entry.stat().st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN)  # ty: ignore[unresolved-attribute]
    except OSError:
        return False


def _exact_paths_rule(paths: Iterable[str]) -> Callable[[str, Any], bool]:
    """Build a rule matching exactly the given relative paths and nothing else.

    A predicate rather than a pattern, so a name holding `[`, `*` or `?` is
    never read as a glob, and a bare name is never matched at another depth.

    Args:
        paths: Relative posix paths, anchored at the root.

    Returns:
        A rule matching only those paths.
    """
    wanted = frozenset(paths)

    def rule(rel: str, entry: Any) -> bool:
        """Match one of the paths.

        Args:
            rel: The relative path.
            entry: The entry, unused.

        Returns:
            Whether `rel` is one of them.
        """
        del entry  # A rule receives it; only the path decides here.
        return rel in wanted

    return rule


def _temp_file_rule(folder: str, prefix: str) -> Callable[[str, Any], bool]:
    """Build a rule matching only `atomic_write`'s temp file for one destination.

    Args:
        folder: The destination's directory relative to the source, ending in `/` or empty.
        prefix: The temp file's name prefix, `.<archive name>.`.

    Returns:
        A rule matching `<folder><prefix>...tmp` and nothing else.
    """
    cut = len(folder)

    def rule(rel: str, entry: Any) -> bool:
        """Match the temp file directly inside `folder`.

        Args:
            rel: The relative path.
            entry: The entry, unused.

        Returns:
            Whether `rel` is the temp file.
        """
        del entry  # A rule receives it; only the path decides here.

        if not rel.startswith(folder):
            return False

        base = rel[cut:]
        return "/" not in base and base.startswith(prefix) and base.endswith(".tmp")

    return rule


def _require_zstd() -> None:
    """Raise the right error unless a zstd backend is available.

    Raises:
        ImportError: Naming the cure; on 3.14 that is a Python built with
            libzstd or the `zstandard` package, before it the `archive` extra.
    """
    if backends.std_zstd is not None or backends.zstandard is not None:
        return

    if sys.version_info >= (3, 14):
        msg = (
            "tar.zst needs zstd support, and this interpreter was built without it -- compression.zstd is part "
            "of the standard library from 3.14, but only when Python was compiled against libzstd. Either use an "
            "interpreter that was, or install the third-party backend: pip install zstandard"
        )
        raise ImportError(msg)

    msg = _build_error_msg(("archive",), _unmet("archive"))
    raise ImportError(msg)


__all__ = (
    "_WalkEntry",
    "_exact_paths_rule",
    "_format_from_suffix",
    "_is_hidden",
    "_new_prefixes",
    "_nt_strip",
    "_require_zstd",
    "_split_workers",
    "_temp_file_rule",
    "_LINK_MAX",
    "_NT",
    "_SUFFIXES",
)
