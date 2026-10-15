"""Writing one member: its directory, its bytes, or its link."""

from __future__ import annotations as _annotations

import io
import logging
import ntpath
import os
import posixpath
import tempfile
from pathlib import Path

from ..._internal._fs import _is_dir, _COPY_BUF
from ...errors import ValidationError
from ...files_tools import ensure_dir, remove_file
from .limiter import _Limiter, _Member

log = logging.getLogger(__name__)


class _WriteMixin:
    """The writes `_Extractor` performs once a member has a target.

    It relies on `_PlaceMixin` for `_under` and `_is_safe_member_name`.
    """

    __slots__ = ()

    src: Path
    dest: Path
    _root: Path
    _limiter: _Limiter
    _made: set[Path]
    _built: list[Path] | None

    def _mkdir(self, path: Path) -> None:
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

    def _link(self, m: _Member, target: Path) -> None:
        """Recreate a link member, if the policy allows and it stays inside the destination.

        A symlink resolves from its own directory, a hardlink from the root;
        either is refused if it would land outside, whatever the policy. A
        directory at the target is never replaced. The link is built beside the
        target and renamed onto it, so a failure leaves what was there alone.

        Args:
            m: The link member, with its destination filled in.
            target: Where it goes.
        """
        raw = m.target

        if not self._limiter.allows_link(m) or not raw or raw.startswith("/") or ntpath.splitdrive(raw)[0]:
            return

        inside = (target.parent if m.kind == "symlink" else self._root).relative_to(self._root).as_posix()
        rel = posixpath.normpath(f"{inside}/{raw}" if inside != "." else raw)
        resolved = self._under(rel) if self._is_safe_member_name(rel) else None

        if resolved is None:
            log.warning("extract_archive: refused %s %r pointing outside %s in %s", m.kind, m.name, self.dest.name, self.src.name)
            return

        if _is_dir(target):
            log.warning("extract_archive: refused %s %r in %s, a directory stands at %r", m.kind, m.name, self.src.name, str(target))
            return

        try:
            # A free name from `mkstemp`, released at once: `os.symlink`/`os.link` refuse an existing path.
            fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
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
            log.warning("extract_archive: could not put %s %r at %r (%s)", m.kind, m.name, str(target), exc)
            return

        if self._built is not None:
            self._built.append(target)

    def _spill(self, m: _Member, data: io.BufferedIOBase, target: Path) -> None:
        """Copy a member's bytes into place in bounded chunks, re-weighing its size as it grows.

        A size different from the header is logged, not fatal. An `OSError`
        skips this member alone.

        Args:
            m: The member.
            data: Its decompressed bytes.
            target: Where they go; its parent already exists.

        Raises:
            ValidationError: If the data ends before its declared size.
            ArchiveLimitError: If it outgrows `max_file_size`.
        """
        grown = 0

        try:
            with open(target, "wb") as out:
                if self._built is not None:
                    self._built.append(target)

                while chunk := data.read(_COPY_BUF):
                    out.write(chunk)
                    grown += len(chunk)
                    self._limiter.grew(m.name, grown)
        except EOFError:
            msg = (
                f"extract_archive: {self.src.name}: member {m.name!r} ends before the {m.size} bytes it declares "
                f"-- the archive is truncated, or its metadata was edited"
            )
            raise ValidationError(msg) from None
        except OSError as exc:
            log.warning("extract_archive: could not write %r from %s (%s)", m.name, self.src.name, exc)
            return

        if grown != m.size:
            log.warning("extract_archive: %s: member %r declares %d bytes but produced %d -- the archive's "
                        "metadata does not describe its contents", self.src.name, m.name, m.size, grown)


__all__ = ("_WriteMixin",)
