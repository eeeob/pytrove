"""The extraction's ceilings and policies, answered in one place."""

from __future__ import annotations as _annotations

import logging
import os
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NamedTuple, NoReturn

from ...enums import ArchiveLinkPolicy, ArchiveOverwritePolicy
from ...errors import ArchiveLimitError, ArchivePolicyError
from ...typings.archive import ArchiveLimits

log = logging.getLogger(__name__)


class _Member(NamedTuple):
    """One archive entry, in the single shape both readers produce.

    Attributes:
        name: The posix member name, without a trailing slash.
        raw: The `ZipInfo` or `TarInfo` it came from, handed to predicate rules.
        size: Its uncompressed size, as the header declares.
        packed: Its compressed size; 0 in a tar, which has no per-member size.
        kind: What it is.
        target: A link's recorded destination; `None` for non-links, and for
            a zip link until its data is read.
    """

    name: str
    raw: zipfile.ZipInfo | tarfile.TarInfo
    size: int
    packed: int
    kind: Literal["dir", "file", "symlink", "hardlink", "other"]
    target: str | None = None


@dataclass(slots=True)
class _Limiter:
    """Every question `ArchiveLimits` answers, with the tallies they need; one per extraction.

    Ceilings are judged from headers before a member's bytes are written,
    then file sizes are re-weighed as bytes really arrive. Only members about
    to be written are counted.

    Attributes:
        limits: The caller's limits.
        src: The archive, named in messages.
        files: Files and links admitted so far.
        total: Bytes they declare.
    """

    limits: ArchiveLimits
    src: Path
    files: int = field(init=False, default=0)
    total: int = field(init=False, default=0)
    _breadth: dict[str, int] = field(init=False, default_factory=dict)
    _counted: set[str] = field(init=False, default_factory=set)
    _seen: set[str] = field(init=False, default_factory=set)
    _taken: set[str] = field(init=False, default_factory=set)

    def count(self, m: _Member) -> None:
        """Weigh one member against every ceiling.

        Directories do not count against `max_files`. Every ancestor a name
        implies is registered once in its parent's breadth, the root's own
        entries against `max_root_entries`. `max_ratio` uses the header's
        packed size, so it is skipped for tar members.

        Args:
            m: The member about to be written.

        Raises:
            ArchiveLimitError: At the first ceiling crossed.
        """
        lim = self.limits
        name = m.name
        size = m.size if m.kind == "file" else 0

        if lim.max_depth is not None and (depth := name.count("/")) > lim.max_depth:
            self._fail(f"member {name!r} is nested {depth} deep, over the {lim.max_depth} allowed")

        if lim.max_dir_entries is not None or lim.max_root_entries is not None:
            parts = name.split("/")

            for i in range(1, len(parts) + 1):
                path = "/".join(parts[:i])

                if path in self._counted:
                    continue

                self._counted.add(path)
                parent = path.rpartition("/")[0]
                self._breadth[parent] = held = self._breadth.get(parent, 0) + 1

                if not parent:
                    if lim.max_root_entries is not None and held > lim.max_root_entries:
                        self._fail(f"the destination holds more than the {lim.max_root_entries} root entries allowed")
                elif lim.max_dir_entries is not None and held > lim.max_dir_entries:
                    self._fail(f"directory {parent!r} holds more than the {lim.max_dir_entries} entries allowed")

        if lim.max_file_size is not None and size > lim.max_file_size:
            self._fail(f"member {name!r} is {size} bytes, over the {lim.max_file_size} allowed")

        if lim.max_ratio is not None and m.packed > 0 and (ratio := size / m.packed) > lim.max_ratio:
            self._fail(f"member {name!r} expands {ratio:.0f}x ({m.packed} -> {size} bytes), "
                       f"over the {lim.max_ratio:g}x allowed")

        if m.kind != "dir":
            self.files += 1
        self.total += size

        if lim.max_files is not None and self.files > lim.max_files:
            self._fail(f"archive holds more than the {lim.max_files} members allowed")

        if lim.max_total_size is not None and self.total > lim.max_total_size:
            self._fail(f"archive expands past the {lim.max_total_size} bytes allowed")

    def grew(self, name: str, member_total: int) -> None:
        """Re-weigh one member's size against `max_file_size` as its bytes are written.

        Args:
            name: The member's name.
            member_total: Bytes written for it so far.

        Raises:
            ArchiveLimitError: If it has outgrown the ceiling.
        """
        lim = self.limits

        if lim.max_file_size is not None and member_total > lim.max_file_size:
            self._fail(f"member {name!r} has written {member_total} bytes, over the {lim.max_file_size} allowed")

    def allows_name(self, name: str) -> bool:
        """Apply `duplicates`: the first member with a name wins.

        Args:
            name: The member's name.

        Returns:
            Whether the name is new.
        """
        if name in self._seen:
            return self._deny(self.limits.duplicates, f"duplicate member {name!r}")

        self._seen.add(name)
        return True

    def allows_target(self, name: str, target: Path) -> bool:
        """Apply `overwrite` to where a member finally comes to rest.

        Keyed on the case-normalised path, so two names landing on one file
        collide too. Nothing is tracked under `OVERWRITE`.

        Args:
            name: The member's name.
            target: Its final path, outside any staging directory.

        Returns:
            Whether it may take that path.
        """
        if self.limits.overwrite == ArchiveOverwritePolicy.OVERWRITE:
            return True

        if target.exists() or (key := os.path.normcase(str(target))) in self._taken:
            return self._deny(self.limits.overwrite, f"member {name!r} already exists")

        self._taken.add(key)
        return True

    def allows_link(self, m: _Member) -> bool:
        """Apply `symlinks` or `hardlinks`; containment is checked separately and always.

        Args:
            m: The link member.

        Returns:
            Whether the policy allows recreating it.
        """
        policy = self.limits.symlinks if m.kind == "symlink" else self.limits.hardlinks

        if policy == ArchiveLinkPolicy.ALLOW:
            return True

        return self._deny(policy, f"{m.kind} member {m.name!r}")

    def allows_dir(self, path: Path) -> bool:
        """Put one extracted directory, with its contents, to `dir_check`.

        Args:
            path: The directory on disk.

        Returns:
            Whether it stays; `None` from the check counts as yes.
        """
        check = self.limits.dir_check

        if check is None:
            return True

        verdict = check(path)

        if verdict is None or verdict:
            return True

        log.warning("extract_archive: dropped directory %r from %s, refused by dir_check", str(path), self.src.name)
        return False

    def _deny(self, policy: str, why: str) -> bool:
        """Refuse a member, raising when the policy is "error" and logging otherwise.

        Compared as a string because several enums reach here and all spell it "error".

        Args:
            policy: The policy that refused.
            why: What was refused.

        Returns:
            Always `False`.

        Raises:
            ArchivePolicyError: When the policy is "error".
        """
        if policy == "error":
            msg = f"extract_archive: {self.src.name}: {why}"
            raise ArchivePolicyError(msg)

        log.info("extract_archive: skipped %s in %s", why, self.src.name)
        return False

    def _fail(self, why: str) -> NoReturn:
        """Stop the extraction for a crossed ceiling.

        Args:
            why: Which ceiling, and by how much.

        Raises:
            ArchiveLimitError: Always.
        """
        msg = f"extract_archive: {self.src.name}: {why}"
        raise ArchiveLimitError(msg)


__all__ = (
    "_Limiter",
    "_Member",
)
