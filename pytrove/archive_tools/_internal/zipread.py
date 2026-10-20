"""Reading a zip archive, optionally on a thread pool."""

from __future__ import annotations as _annotations

import logging
import os
import stat
import threading
import zipfile
from concurrent.futures import Executor, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, TYPE_CHECKING, cast

from ...errors import ValidationError
from .common import _split_workers, _LINK_MAX
from .limiter import _Member

log = logging.getLogger(__name__)


@dataclass(slots=True)
class _ZipReaders:
    """One open `ZipFile` per thread, since two threads seeking one handle read each other's bytes.

    Attributes:
        src: The archive.
        pwd: The password for encrypted members.
    """

    src: Path
    pwd: bytes | None
    _local: threading.local = field(init=False, default_factory=threading.local)
    _all: list[zipfile.ZipFile] = field(init=False, default_factory=list)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)

    def get(self) -> zipfile.ZipFile:
        """Return the calling thread's handle, opening it on first use.

        Returns:
            The handle.
        """
        zf = getattr(self._local, "zf", None)

        if zf is None:
            zf = zipfile.ZipFile(self.src)

            if self.pwd is not None:
                zf.setpassword(self.pwd)

            self._local.zf = zf

            with self._lock:
                self._all.append(zf)

        return zf

    def close(self) -> None:
        """Close every handle any thread opened."""
        with self._lock:
            handles, self._all = self._all, []

        for zf in handles:
            try:
                zf.close()
            except OSError:
                pass


class _ZipMixin:
    """The zip half of `_Extractor`: one streaming pass over the central directory.

    The main thread decides every path and makes every directory; a worker
    only writes its own member, or reads and creates a zip link.
    """

    __slots__ = ()

    src: Path
    password: bytes | None

    if TYPE_CHECKING:
        # Provided by `_PlaceMixin` and `_WriteMixin` in `_Extractor`; declared so `ty` can check the calls made through `self`.
        def _place(self, m: _Member) -> Path | None: ...
        def _mkdir(self, path: Path) -> None: ...
        def _link(self, m: _Member, target: Path) -> None: ...
        def _spill(self, m: _Member, data: IO[bytes], target: Path) -> None: ...

    def _zip_copy(self, readers: _ZipReaders, m: _Member, target: Path) -> None:
        """Write one member, on whichever thread runs this.

        A zip link's destination lives in its data, so it is read here,
        bounded by `_LINK_MAX`, and handed to `_link`.

        Args:
            readers: The per-thread handles.
            m: The member.
            target: Where it goes.

        Raises:
            ValidationError: For WinZip AES, an encrypted member without a
                password, a wrong password or an unsupported compression method.
        """
        # `_zip` builds every member it hands here from a `ZipInfo`; `_Member.raw` is
        # the union both readers share, so the zip side states its own arm.
        info = cast(zipfile.ZipInfo, m.raw)

        if info.compress_type == 99:
            msg = f"extract_archive: {self.src.name}: member {m.name!r} uses WinZip AES encryption, which the standard library cannot read"
            raise ValidationError(msg)

        if info.flag_bits & 0x1 and self.password is None:
            msg = f"extract_archive: {self.src.name}: member {m.name!r} is encrypted -- pass password=... to extract it"
            raise ValidationError(msg)

        try:
            data = readers.get().open(info)
        except (RuntimeError, NotImplementedError) as exc:
            msg = f"extract_archive: {self.src.name}: member {m.name!r}: {exc}"
            raise ValidationError(msg) from None

        with data:
            if m.kind == "file":
                self._spill(m, data, target)
                return

            try:
                raw = data.read(_LINK_MAX + 1)
            except OSError as exc:
                log.warning("extract_archive: could not read the destination of %s %r in %s (%s)",
                            m.kind, m.name, self.src.name, exc)
                return

        if len(raw) > _LINK_MAX:
            log.warning("extract_archive: refused %s %r in %s, its destination is longer than %d bytes",
                        m.kind, m.name, self.src.name, _LINK_MAX)
            return

        self._link(m._replace(target=os.fsdecode(raw)), target)

    def _zip(self, workers: int | Executor | None = None) -> None:
        """Read the central directory and write every member that passes, in one pass.

        With `workers`, writes run on a pool (zlib releases the GIL); two
        members landing on one path are serialised, and at most a few batches
        are kept in flight.

        Args:
            workers: A thread count or a pool.
        """
        count, pool = _split_workers(workers, "extract_archive")
        own = ThreadPoolExecutor(count) if count and count > 1 else None
        pool = pool or own
        readers = _ZipReaders(self.src, self.password)
        inflight: dict[str, Future[None]] = {}
        ahead = 4 * (count or 8)

        try:
            for info in readers.get().infolist():
                kind = stat.S_IFMT(info.external_attr >> 16)
                m = _Member(
                    info.filename.replace("\\", "/").rstrip("/"),
                    info,
                    info.file_size,
                    info.compress_size,
                    "dir" if info.is_dir()
                    else "file" if not kind
                    else "symlink" if kind == stat.S_IFLNK
                    else "file" if kind == stat.S_IFREG
                    else "other",
                )
                target = self._place(m)

                if target is None:
                    continue

                if m.kind == "dir":
                    self._mkdir(target)
                    continue

                self._mkdir(target.parent)

                if pool is None:
                    self._zip_copy(readers, m, target)
                    continue

                key = os.path.normcase(str(target))

                if (earlier := inflight.pop(key, None)) is not None:
                    earlier.result()

                inflight[key] = pool.submit(self._zip_copy, readers, m, target)

                while len(inflight) > ahead:
                    done_key = next(iter(inflight))
                    done_job = inflight[done_key]
                    done_job.result()

                    if inflight.get(done_key) is done_job:
                        del inflight[done_key]

            for job in inflight.values():
                job.result()
        finally:
            try:
                for job in inflight.values():
                    job.cancel()

                wait(inflight.values())
            finally:
                try:
                    if own is not None:
                        own.shutdown(wait=False, cancel_futures=True)
                finally:
                    readers.close()


__all__ = (
    "_ZipMixin",
    "_ZipReaders",
)
