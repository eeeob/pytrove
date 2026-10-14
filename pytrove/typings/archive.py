"""Types belonging to `archive_tools`.

`ArchiveLimits` lives here rather than beside the extractor because callers
build it and pass it to `extract_archive`, so it is part of the interface.
"""

from __future__ import annotations as _annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from ..enums import ArchiveDuplicatePolicy, ArchiveLinkPolicy, ArchiveOverwritePolicy


class ArchiveLimits(NamedTuple):
    """What `extract_archive` may write, and what it may write it as.

    Immutable, hashable and comparable by value, so one instance can be
    shared by any number of calls. The ceilings default to `None` (no
    ceiling) because no single number suits every archive; the policies
    default to the safe answer. A misspelled policy string matches no
    branch and so falls back to the conservative behaviour. An absolute or
    `..` member name is always refused, whatever these settings say.

    Attributes:
        max_files: Most files and links written; directories are not counted.
        max_total_size: Most bytes written in total.
        max_file_size: Most bytes written for any one member.
        max_ratio: Highest declared-to-stored size ratio for one member, the
            zip-bomb check. Legitimate ratios above 1000 exist, so it is a policy.
        max_depth: Deepest directory nesting allowed.
        max_dir_entries: Most entries in any one directory below the root,
            counting the directories a member's path implies.
        max_root_entries: Most entries directly in the destination root.
        dir_check: Called once per extracted directory, outermost first, with
            its on-disk staging path. Return a falsy value to drop that subtree,
            raise to abort. Judge it by name or contents, not by location: it
            runs inside a staging directory beside `dest`.
        symlinks: What to do with a symlink member.
        hardlinks: What to do with a hardlink member.
        overwrite: What to do when a member's path is already taken.
        duplicates: What to do with a member name seen before.
    """

    max_files: int | None = None
    max_total_size: int | None = None
    max_file_size: int | None = None
    max_ratio: float | None = None
    max_depth: int | None = None
    max_dir_entries: int | None = None
    max_root_entries: int | None = None
    dir_check: Callable[[Path], bool | None] | None = None

    symlinks: ArchiveLinkPolicy = ArchiveLinkPolicy.ERROR
    hardlinks: ArchiveLinkPolicy = ArchiveLinkPolicy.ERROR
    overwrite: ArchiveOverwritePolicy = ArchiveOverwritePolicy.OVERWRITE
    duplicates: ArchiveDuplicatePolicy = ArchiveDuplicatePolicy.SKIP

    @classmethod
    def permissive(cls, **kw: Any) -> ArchiveLimits:
        """Build limits that restore links, for an archive you made yourself.

        A link pointing outside the destination is still refused, and the
        ceilings are untouched.

        Args:
            **kw: Any other field to set.

        Returns:
            Limits with `symlinks` and `hardlinks` set to `ArchiveLinkPolicy.ALLOW`.
        """
        return cls(symlinks=ArchiveLinkPolicy.ALLOW, hardlinks=ArchiveLinkPolicy.ALLOW, **kw)


__all__ = ("ArchiveLimits",)
