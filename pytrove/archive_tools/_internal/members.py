"""Writing one member: its directory, its bytes, or its link."""

from __future__ import annotations as _annotations

import logging
import ntpath
import os
import posixpath
import secrets
import tempfile
from pathlib import Path
from typing import IO, TYPE_CHECKING

from ..._internal import _is_dir, _COPY_BUF
from ...errors import ValidationError
from ...files_tools import ensure_dir, remove_file

if TYPE_CHECKING:
    from .extractor import _Extractor
    from .limiter import _Member

log = logging.getLogger(__name__)


class _WriteMixin:
    """The writes `_Extractor` performs once a member has a target.

    It relies on `_PlaceMixin` for `_under` and `_is_safe_member_name`.
    """

    __slots__ = ()

    def _mkdir(self: _Extractor, path: Path) -> None:
        """Create a directory once, recording each level this run brings into being.

        Args:
            path: The directory.

        Raises:
            OSError: If it cannot be created; nothing under it could be written.
        """
        if path in self._made:
            return

        fresh = []

        while path != self._root and path != path.parent and not path.exists():
            fresh.append(path)
            path = path.parent

        if not fresh:
            self._made.add(path)
            return

        for level in reversed(fresh):
            ensure_dir(level, parents=False, exist_ok=True)

        self._made.update(fresh)

        if self._built is not None:
            self._built.extend(reversed(fresh))

    def _link(self: _Extractor, m: _Member, target: Path) -> None:
        """Recreate a link member that stays inside the destination; `_place` already applied the policy.

        A symlink resolves from its own directory, a hardlink from the root;
        either is refused if it would land outside, whatever the policy. That
        is judged on the text, and on the path the operating system really
        reaches, following every link already extracted, so a target that
        backs out (`..`) through an earlier link is caught. A symlink whose
        target climbs (`..`) after descending is refused too: a later member
        could turn what it descends through into a link (`l -> m/..`, then
        `m -> .`), which neither check can see yet; its leading `..` climb from
        a parent already resolved, and each link it descends through was itself
        checked when it was made. An empty, absolute or drive-letter target is
        refused. A directory at the target
        is never replaced. The link is built beside the target and renamed onto
        it, so a failure leaves what was there alone.

        Args:
            m: The link member, with its destination filled in.
            target: Where it goes.
        """
        raw = m.target

        if not raw or raw.startswith(("/", "\\")) or ntpath.splitdrive(raw)[0]:
            log.warning(
                "extract_archive: refused %s %r in %s, its destination %r is empty or absolute",
                m.kind,
                m.name,
                self.src.name,
                raw,
            )
            return

        base = target.parent if m.kind == "symlink" else self._root
        inside = base.relative_to(self._root).as_posix()
        rel = posixpath.normpath(f"{inside}/{raw}" if inside != "." else raw)
        resolved = self._under(rel) if self._is_safe_member_name(rel) else None

        if m.kind == "symlink":
            # `\` counts as a separator too: refusing a rare POSIX name is safer than missing a climb.
            segs = [s for s in raw.replace("\\", "/").split("/") if s not in ("", ".")]
            climb = next((i for i, s in enumerate(segs) if s != ".."), len(segs))

            if ".." in segs[climb:]:
                resolved = None

        if resolved is not None:
            try:
                real = (base / raw).resolve(strict=False)
            except (OSError, RuntimeError, ValueError):  # A loop, an unreadable link, a NUL.
                resolved = None
            else:
                resolved = real if real.is_relative_to(self._root) else None

        if resolved is None:
            log.warning(
                "extract_archive: refused %s %r pointing outside %s in %s",
                m.kind,
                m.name,
                self.dest.name,
                self.src.name,
            )
            return

        if _is_dir(target):
            log.warning(
                "extract_archive: refused %s %r in %s, a directory stands at %r",
                m.kind,
                m.name,
                self.src.name,
                str(target),
            )
            return

        try:
            # A free name from `mkstemp`, released at once: `os.symlink`/`os.link` refuse an existing path.
            fd, tmp_name = tempfile.mkstemp(
                dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
            )
            os.close(fd)
            os.unlink(tmp_name)
            tmp = Path(tmp_name)

            if m.kind == "symlink":
                os.symlink(raw, tmp)
            else:
                os.link(resolved, tmp)
        except OSError as exc:
            log.warning("extract_archive: could not create %s %r (%s)", m.kind, m.name, exc)
            return

        try:
            os.replace(tmp, target)
        except OSError as exc:
            remove_file(tmp, return_exc=True, log_exc=True)
            log.warning(
                "extract_archive: could not put %s %r at %r (%s)", m.kind, m.name, str(target), exc
            )
            return

        if self._built is not None:
            self._built.append(target)

    def _spill(self: _Extractor, m: _Member, data: IO[bytes], target: Path) -> None:
        """Copy a member's bytes into place in bounded chunks, re-weighing its size as it grows.

        A new path is created exclusively. Whatever already stands at the path
        (a link, perhaps pointing outside `dest`, or a hardlink shared with a
        file elsewhere) is never written through: the bytes go to a temp file
        beside it, created with the mode a new file gets, which then replaces
        it. A size different from the header is
        logged, not fatal. An `OSError` skips this member alone.

        Args:
            m: The member.
            data: Its decompressed bytes.
            target: Where they go; its parent already exists.

        Raises:
            ValidationError: If the data ends before its declared size.
            ArchiveLimitError: If it outgrows `max_file_size`.
        """
        grown = 0
        tmp: str | None = None

        try:
            try:
                out = open(
                    target, "xb"
                )  # Closed by the `with` below, as is the temp file's handle.
            except FileExistsError:
                # Not `mkstemp`, which forces mode 0600: `xb` gives the temp file the mode a new one gets.
                tmp = str(target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp"))
                out = open(tmp, "xb")  # Closed by the `with` below.

            with out:
                if self._built is not None and tmp is None:
                    self._built.append(target)

                while chunk := data.read(_COPY_BUF):
                    out.write(chunk)
                    grown += len(chunk)
                    self._limiter.grew(m.name, grown)

            if tmp is not None:
                os.replace(tmp, target)
                tmp = None

                if self._built is not None:
                    self._built.append(target)
        except EOFError:
            msg = (
                f"extract_archive: {self.src.name}: member {m.name!r} ends before the {m.size} bytes it declares "
                f"-- the archive is truncated, or its metadata was edited"
            )
            raise ValidationError(msg) from None
        except OSError as exc:
            log.warning(
                "extract_archive: could not write %r from %s (%s)", m.name, self.src.name, exc
            )
            return
        finally:
            if tmp is not None:
                remove_file(tmp, return_exc=True)

        if grown != m.size:
            log.warning(
                "extract_archive: %s: member %r declares %d bytes but produced %d -- the archive's "
                "metadata does not describe its contents",
                self.src.name,
                m.name,
                m.size,
                grown,
            )


__all__ = ("_WriteMixin",)
