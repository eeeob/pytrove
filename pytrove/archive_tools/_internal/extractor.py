"""Turning an archive back into files: staging, inspection and the final move."""

from __future__ import annotations as _annotations

import logging
import os
import tempfile
from collections import deque
from concurrent.futures import Executor
from dataclasses import dataclass, field
from pathlib import Path

from ..._internal._fs import _is_dir, _is_link
from ...enums import ArchiveFormat
from ...errors import ValidationError
from ...files_tools import remove_file, remove_folder, remove_path, remove_paths
from ...iter_tools import dedupe
from ...typings.archive import ArchiveLimits
from .common import _format_from_suffix
from .limiter import _Limiter
from .members import _WriteMixin
from .placement import _PlaceMixin
from .rules import _Filter
from .tarread import _TarMixin
from .zipread import _ZipMixin

log = logging.getLogger(__name__)


@dataclass(slots=True)
class _Extractor(_PlaceMixin, _WriteMixin, _ZipMixin, _TarMixin):
    """Extracts one archive, refusing what must not be written; build one per call.

    Both formats are read into `_Member` and pass the same gate, `_place`.

    Attributes:
        src: The archive.
        dest: The destination directory.
        flt: What to keep.
        limits: Ceilings and policies.
        password: For encrypted zip members.
    """

    src: Path
    dest: Path
    flt: _Filter
    limits: ArchiveLimits = ArchiveLimits()
    password: bytes | None = None
    _root: Path = field(init=False)
    _limiter: _Limiter = field(init=False)
    _cleared: dict[str, Path | None] = field(init=False, default_factory=dict)
    _ancestry: dict[str, bool] = field(init=False, default_factory=dict)
    _made: set[Path] = field(init=False, default_factory=set)
    _built: list[Path] | None = field(init=False, default=None)

    def run(
        self,
        fmt: ArchiveFormat,
        workers: int | Executor | None = None,
        atomic: bool = False,
        cleanup_on_error: bool = False,
    ) -> None:
        """Extract the archive, staging it beside `dest` when `atomic` or a `dir_check` asks.

        A staged tree is renamed onto a missing `dest`, else merged into it
        (not atomic). If that last step fails the staged tree is kept and
        named in the log. Without staging, `cleanup_on_error` removes what this
        run created, and nothing that existed before.

        Args:
            fmt: The archive's format.
            workers: A thread count or a pool, for zip.
            atomic: Whether to stage the whole extraction first.
            cleanup_on_error: Whether to undo a failed unstaged run.

        Raises:
            NotADirectoryError: If `dest` exists and is not a directory.
        """
        if self.dest.exists() and not self.dest.is_dir():
            msg = f"extract_archive: {str(self.dest)!r} exists and is not a directory"
            raise NotADirectoryError(msg)

        staged = None

        if atomic or self.limits.dir_check is not None:
            staged = Path(tempfile.mkdtemp(prefix=f".{self.dest.name}.", suffix=".tmp", dir=self.dest.parent))

        self._root = staged or self.dest
        self._limiter = _Limiter(self.limits, self.src)
        self._built = [] if cleanup_on_error and staged is None else None

        if self._built is not None and not self._root.exists():
            self._built.append(self._root)

        try:
            self._root.mkdir(exist_ok=True)

            if fmt is ArchiveFormat.ZIP:
                self._zip(workers)
            else:
                self._tar(fmt, workers)

            self._inspect(self._root)
        except BaseException:
            if staged is not None:
                remove_path(staged, return_exc=True, log_exc=True)
            elif self._built:
                remove_paths(dedupe(self._built), return_exc=True, log_exc=True)
            raise

        if staged is None:
            return

        # Nothing is cleared to make room: removing `dest` first and failing the rename after loses both.
        try:
            try:
                os.replace(staged, self.dest)
            except OSError:
                if not self.dest.exists():
                    raise

                self._graft(staged, self.dest)
                remove_path(staged, return_exc=True, log_exc=True)
        except BaseException:
            log.error("extract_archive: could not put %s at %r -- what came out of it is in %r",
                      self.src.name, str(self.dest), str(staged))
            raise

    def _inspect(self, root: Path) -> None:
        """Put every extracted directory to `dir_check`, outermost first, removing refused subtrees.

        Args:
            root: The staging directory.
        """
        if self.limits.dir_check is None:
            return

        stack = deque([root])

        while stack:
            here = stack.popleft()

            try:
                with os.scandir(here) as it:
                    entries = list(it)
            except OSError as exc:
                log.warning("extract_archive: cannot read back %r (%s)", str(here), exc)
                continue

            for entry in entries:
                if not _is_dir(entry.path):
                    continue

                path = Path(entry.path)

                if self._limiter.allows_dir(path):
                    stack.append(path)
                else:
                    remove_folder(path, return_exc=True, log_exc=True)

    def _graft(self, staged: Path, dest: Path) -> None:
        """Merge a staged tree into an existing destination, without recursion.

        A real directory on both sides is merged into; a link or junction in
        `dest` is never followed; a directory in `dest` is never replaced by
        anything that is not one; anything else is replaced.

        Args:
            staged: The staging directory.
            dest: The destination.
        """
        pairs = [(staged, dest)]

        while pairs:
            here, there = pairs.pop()

            with os.scandir(here) as it:  # Closed before moving: an open handle blocks removal on Windows.
                entries = list(it)

            for entry in entries:
                target = there / entry.name

                if _is_dir(entry.path) and _is_dir(target):
                    pairs.append((Path(entry.path), target))
                    continue

                if _is_dir(target):
                    log.warning("extract_archive: refused %r from %s, a directory stands at %r",
                                entry.name, self.src.name, str(target))
                    continue

                if _is_link(target):  # `os.replace` cannot take a path from a directory reparse point.
                    remove_file(target)

                os.replace(entry.path, target)

    @staticmethod
    def detect_format(path: str) -> ArchiveFormat:
        """Identify an archive by its leading bytes, falling back to its name.

        Args:
            path: The archive.

        Returns:
            Its format.

        Raises:
            ValidationError: If neither the content nor the name tells.
        """
        try:
            with open(path, "rb") as f:
                head = f.read(4)
        except OSError:
            head = b""

        magics = (
            (b"PK\x03\x04", ArchiveFormat.ZIP),
            (b"PK\x05\x06", ArchiveFormat.ZIP),  # An empty zip.
            (b"\x1f\x8b", ArchiveFormat.TAR_GZ),
            (b"\x28\xb5\x2f\xfd", ArchiveFormat.TAR_ZST),
        )

        for magic, fmt in magics:
            if head and head.startswith(magic):
                return fmt

        if (fmt := _format_from_suffix(path)) is not None:
            return fmt

        msg = f"extract_archive: cannot tell what format {path!r} is"
        raise ValidationError(msg)


__all__ = ("_Extractor",)
