"""The extraction's ceilings and policies, answered in one place."""

from __future__ import annotations as _annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NamedTuple, NoReturn, TypeVar

from ...enums import ArchiveDuplicatePolicy, ArchiveLinkPolicy, ArchiveOverwritePolicy
from ...errors import ArchiveLimitError, ArchivePolicyError, ValidationError
from ...typings.archive import ArchiveLimits
from .common import _new_prefixes, _nt_strip, _NT

if TYPE_CHECKING:
    import tarfile
    import zipfile

log = logging.getLogger(__name__)

_PolicyT = TypeVar("_PolicyT", ArchiveLinkPolicy, ArchiveOverwritePolicy, ArchiveDuplicatePolicy)
"""One of the policy enums `_policy` coerces to."""


class _Member(NamedTuple):
    """One archive entry, in the single shape both readers produce."""

    name: str
    """The posix member name, without a trailing slash."""

    raw: zipfile.ZipInfo | tarfile.TarInfo
    """The header it came from, handed to predicate rules."""

    size: int
    """Its uncompressed size, as the header declares."""

    packed: int
    """Its compressed size; 0 in a tar, which has no per-member size, so `max_ratio` skips it."""

    kind: Literal["dir", "file", "symlink", "hardlink", "other"]
    """What it is; `"other"` (a device, fifo, ...) is never written."""

    target: str | None = None
    """A link's recorded destination; `None` for non-links, and for a zip link until its data is read."""


@dataclass(slots=True)
class _Limiter:
    """Every question `ArchiveLimits` answers, with the tallies they need; one per extraction.

    Ceilings are judged from headers before a member's bytes are written,
    then file sizes are re-weighed as bytes really arrive. Only members about
    to be written are counted.
    """

    limits: ArchiveLimits
    """The caller's limits."""

    src: Path
    """The archive, named in messages."""

    files: int = field(init=False, default=0)
    """Files and links admitted so far, against `max_files`."""

    total: int = field(init=False, default=0)
    """Bytes the admitted files declare, against `max_total_size`."""

    _breadth: dict[str, int] = field(init=False, default_factory=dict)
    """Entries registered per directory name (`""` for the root), against `max_dir_entries`/`max_root_entries`."""

    _counted: set[str] = field(init=False, default_factory=set)
    """Every path already registered in `_breadth`, so an implied directory counts once."""

    _seen: set[str] = field(init=False, default_factory=set)
    """Member names already admitted, for `duplicates`, as `_name_key` spells them."""

    _taken: set[str] = field(init=False, default_factory=set)
    """Case-normalised final paths already claimed, for `overwrite`; empty under `OVERWRITE`."""

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
            for path in _new_prefixes(name, self._counted):
                parent = path.rpartition("/")[0]
                self._breadth[parent] = held = self._breadth.get(parent, 0) + 1

                if not parent:
                    if lim.max_root_entries is not None and held > lim.max_root_entries:
                        self._fail(
                            f"the destination holds more than the {lim.max_root_entries} root entries allowed"
                        )
                elif lim.max_dir_entries is not None and held > lim.max_dir_entries:
                    self._fail(
                        f"directory {parent!r} holds more than the {lim.max_dir_entries} entries allowed"
                    )

        if lim.max_file_size is not None and size > lim.max_file_size:
            self._fail(f"member {name!r} is {size} bytes, over the {lim.max_file_size} allowed")

        if (
            lim.max_ratio is not None
            and m.packed > 0
            and (ratio := size / m.packed) > lim.max_ratio
        ):
            self._fail(
                f"member {name!r} expands {ratio:.0f}x ({m.packed} -> {size} bytes), "
                f"over the {lim.max_ratio:g}x allowed"
            )

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
            self._fail(
                f"member {name!r} has written {member_total} bytes, over the {lim.max_file_size} allowed"
            )

    @staticmethod
    def _name_key(name: str) -> str:
        """Spell a member name the way the filesystem will see it, so two names for one path compare equal.

        `.` segments are dropped; on Windows trailing dots and spaces are
        stripped from each segment, as the filesystem does. Case is kept: two
        names differing only in case are distinct names, and where they land
        on one file `overwrite` decides.

        Args:
            name: The member's posix name.

        Returns:
            The key `duplicates` is judged on.
        """
        if _NT:
            return _nt_strip(name)

        return "/".join(p for p in name.split("/") if p != ".")

    def allows_name(self, name: str) -> bool:
        """Apply `duplicates`: the first member with a name wins.

        `a.txt`, `./a.txt` and `d/./a.txt`-style spellings of one path are
        the same name.

        Args:
            name: The member's name.

        Returns:
            Whether the name is new.
        """
        if (key := self._name_key(name)) in self._seen:
            return self._deny(self.limits.duplicates, f"duplicate member {name!r}")

        self._seen.add(key)
        return True

    def forget(self, name: str) -> None:
        """Free a name `allows_name` admitted, for a member that ended up not written.

        Args:
            name: The member's name.
        """
        self._seen.discard(self._name_key(name))

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

        log.warning(
            "extract_archive: dropped directory %r from %s, refused by dir_check",
            str(path),
            self.src.name,
        )
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


def _checked_limits(limits: object) -> ArchiveLimits:
    """Check `extract_archive`'s `limits` up front, coercing policy strings to their enums.

    Args:
        limits: What the caller passed.

    Returns:
        The limits, with every policy an enum member.

    Raises:
        ValidationError: For anything but an `ArchiveLimits`, a ceiling that is
            not `None` or a non-negative number (`max_ratio` may be a float,
            the rest are ints), a `dir_check` that is not callable, or an
            unknown policy.
    """
    if not isinstance(limits, ArchiveLimits):
        msg = f"extract_archive: limits takes an ArchiveLimits, not {type(limits).__name__}"
        raise ValidationError(msg)

    ceilings = (
        "max_files",
        "max_total_size",
        "max_file_size",
        "max_ratio",
        "max_depth",
        "max_dir_entries",
        "max_root_entries",
    )

    for name in ceilings:
        value = getattr(limits, name)
        kinds = (int, float) if name == "max_ratio" else (int,)

        if value is not None and (
            not isinstance(value, kinds) or isinstance(value, bool) or value < 0
        ):
            msg = (
                f"extract_archive: limits.{name} takes None or a non-negative number, not {value!r}"
            )
            raise ValidationError(msg)

    if limits.dir_check is not None and not callable(limits.dir_check):
        msg = (
            f"extract_archive: limits.dir_check takes None or a callable, not {limits.dir_check!r}"
        )
        raise ValidationError(msg)

    return limits._replace(
        symlinks=_policy(ArchiveLinkPolicy, "symlinks", limits.symlinks),
        hardlinks=_policy(ArchiveLinkPolicy, "hardlinks", limits.hardlinks),
        overwrite=_policy(ArchiveOverwritePolicy, "overwrite", limits.overwrite),
        duplicates=_policy(ArchiveDuplicatePolicy, "duplicates", limits.duplicates),
    )


def _policy(enum: type[_PolicyT], name: str, value: object) -> _PolicyT:
    """Coerce one policy field to its enum.

    Args:
        enum: The policy's enum.
        name: The field, for the message.
        value: A member or its string value.

    Returns:
        The member.

    Raises:
        ValidationError: For anything else.
    """
    try:
        return enum(value)
    except ValueError:
        msg = (
            f"extract_archive: limits.{name} takes one of "
            f"{', '.join(repr(m.value) for m in enum)}, not {value!r}"
        )
        raise ValidationError(msg) from None


__all__ = (
    "_Limiter",
    "_Member",
    "_PolicyT",
    "_checked_limits",
    "_policy",
)
