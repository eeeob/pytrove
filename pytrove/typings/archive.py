"""Types belonging to `archive_tools`.

`ArchiveLimits` lives here rather than beside the extractor because callers
build it and pass it to `extract_archive`, so it is part of the interface.
"""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from ..enums import ArchiveDuplicatePolicy, ArchiveLinkPolicy, ArchiveOverwritePolicy

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class ArchiveLimits(NamedTuple):
    """What `extract_archive` may write, and what it may write it as.

    Immutable, hashable and comparable by value, so one instance can be
    shared by any number of calls. The ceilings default to `None` (no
    ceiling) because no single number suits every archive; the policies
    default to the safe answer. A misspelled policy string matches no
    branch and so falls back to the conservative behaviour. An absolute or
    `..` member name is always refused, whatever these settings say.
    """

    max_files: int | None = None
    """Most files and links written; directories are not counted."""

    max_total_size: int | None = None
    """Most bytes written in total, summed from the headers' declared sizes."""

    max_file_size: int | None = None
    """Most bytes for any one member: checked from its header, then again as its bytes arrive."""

    max_ratio: float | None = None
    """Highest declared-to-stored size ratio for one member, the zip-bomb check; tar members are exempt."""

    max_depth: int | None = None
    """Deepest directory nesting allowed, counted as `/` separators in the member name."""

    max_dir_entries: int | None = None
    """Most entries in any one directory below the root, counting the directories a path implies."""

    max_root_entries: int | None = None
    """Most entries directly in the destination root."""

    dir_check: Callable[[Path], bool | None] | None = None
    """Called per extracted directory, outermost first, with its staging path; falsy drops the subtree, raising aborts."""

    symlinks: ArchiveLinkPolicy = ArchiveLinkPolicy.ERROR
    """What to do with a symlink member."""

    hardlinks: ArchiveLinkPolicy = ArchiveLinkPolicy.ERROR
    """What to do with a hardlink member."""

    overwrite: ArchiveOverwritePolicy = ArchiveOverwritePolicy.OVERWRITE
    """What to do when a member's path is already taken."""

    duplicates: ArchiveDuplicatePolicy = ArchiveDuplicatePolicy.SKIP
    """What to do with a member name seen before; the first one always wins."""

    @classmethod
    def permissive(cls, **kw: Any) -> ArchiveLimits:
        """Build limits that restore links, for an archive you made yourself.

        A link pointing outside the destination is still refused, and the
        ceilings are untouched.

        Args:
            **kw: Any other field to set, `symlinks` or `hardlinks` included.

        Returns:
            Limits with `symlinks` and `hardlinks` set to `ArchiveLinkPolicy.ALLOW`
            unless `kw` sets them.
        """
        kw.setdefault("symlinks", ArchiveLinkPolicy.ALLOW)
        kw.setdefault("hardlinks", ArchiveLinkPolicy.ALLOW)
        return cls(**kw)


__all__ = ("ArchiveLimits",)
