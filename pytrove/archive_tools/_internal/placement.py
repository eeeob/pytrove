"""Where an archive member may land, if anywhere."""

from __future__ import annotations as _annotations

import logging
import ntpath
from functools import partial
from pathlib import Path
from typing import Any

from ...callable_tools import safe_call
from .common import _NT
from .limiter import _Limiter, _Member
from .rules import _Filter

log = logging.getLogger(__name__)


class _PlaceMixin:
    """The checks that turn an archive's member name into a path, for `_Extractor`.

    An archive is untrusted: a name like `../../etc/x` or `C:/x` must never
    leave the destination. Header checks run first, then the filesystem is
    asked as late as possible, since an earlier link member changes where
    later names resolve.
    """

    __slots__ = ()

    src: Path
    dest: Path
    flt: _Filter
    _root: Path
    _limiter: _Limiter
    _cleared: dict[str, Path | None]
    _ancestry: dict[str, bool]

    def _member_kept(self, m: _Member) -> bool:
        """Apply the filter as a walk would, pruning at each directory the name passes through.

        `_ancestry` memoises `enter` per directory; finding a branch there proves
        every level above it was entered.

        Args:
            m: The member.

        Returns:
            Whether the filter keeps it.
        """
        head = m.name.rpartition("/")[0]

        if head:
            if (ok := self._ancestry.get(head)) is None:
                parts = head.split("/")

                for i in range(1, len(parts) + 1):
                    branch = "/".join(parts[:i])

                    if (ok := self._ancestry.get(branch)) is None:
                        self._ancestry[branch] = ok = self.flt.enter(branch)

                    if not ok:
                        break

            if not ok:
                return False

        return self.flt.matches(m.name, m.raw)

    def _under(self, name: str) -> Path | None:
        """Resolve a posix name under the root, through a per-directory cache.

        On Windows trailing dots and spaces are stripped from each component
        first, as the filesystem would, so one file gives one key. The cache is
        filled with `setdefault` because this also runs on pool workers.

        Args:
            name: A name already judged safe.

        Returns:
            The path that will really be written, or `None` if it leaves the root.
        """
        if _NT:
            name = "/".join(part for raw in name.split("/") if (part := raw.rstrip(". ")))

            if not name:
                return None

        parent, _, base = name.rpartition("/")

        try:
            safe = self._cleared[parent]
        except KeyError:
            if parent:
                resolved = safe_call(
                    partial((self._root / parent).resolve, strict=False), include_exc=(ValueError, OSError), log_exc=True,
                )
                computed = resolved if resolved is not None and resolved.is_relative_to(self._root) else None
            else:
                computed = self._root

            safe = self._cleared.setdefault(parent, computed)

        return None if safe is None else safe / base

    def _place(self, m: _Member) -> Path | None:
        """Decide where a member goes, just before it is written.

        Header checks first (kind, name, filter, duplicates), then the path,
        then `overwrite` against the final location, and only then the
        ceilings, so a refused member spends none of them.

        Args:
            m: The member.

        Returns:
            Its target, or `None` if it is not to be written.
        """
        name = m.name

        if (
            m.kind == "other"
            or not self._is_safe_member_name(name)
            or (self.flt and not self._member_kept(m))
            or not self._limiter.allows_name(name)
        ):
            return None

        target = self._under(name)

        if target is None:
            self._limiter._seen.discard(name)
            log.warning("extract_archive: refused member %r in %s, it resolves outside the destination", name, self.src.name)
            return None

        final = target if self._root == self.dest else self.dest / target.relative_to(self._root)

        if m.kind != "dir" and not self._limiter.allows_target(name, final):
            self._limiter._seen.discard(name)  # It was never written, so the name is free again.
            return None

        self._limiter.count(m)
        return target

    def _is_safe_member_name(self, name: Any) -> bool:
        """Judge a member name by its text alone.

        Refused: non-strings, empty names, NUL, backslashes (a separator on
        Windows, which would defeat the directory cache), absolute names,
        drive letters, and any segment that is empty or `..` once its
        surrounding whitespace is stripped (so ` ..` cannot slip through).
        `.` is allowed.

        Args:
            name: The posix member name.

        Returns:
            Whether it may be written at all; a refusal is logged.
        """
        is_safe = bool(
            isinstance(name, str)
            and name
            and "\x00" not in name
            and "\\" not in name
            and not name.startswith("/")
            and not ntpath.splitdrive(name)[0]
            and not any(part.strip() in ("..", "") for part in name.split("/"))
        )

        if not is_safe:
            log.warning("extract_archive: refused unsafe member name %r in %s", name, self.src.name)

        return is_safe


__all__ = ("_PlaceMixin",)
