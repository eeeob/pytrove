"""Reading a compressed tar archive."""

from __future__ import annotations as _annotations

import gzip
import logging
import tarfile
from typing import IO, TYPE_CHECKING, Any

from ...enums import ArchiveFormat
from . import backends
from .limiter import _Member

if TYPE_CHECKING:
    from concurrent.futures import Executor

    from .extractor import _Extractor

log = logging.getLogger(__name__)


class _TarMixin:
    """The tar half of `_Extractor`: one in-order pass over the stream, writing as it reads."""

    __slots__ = ()

    def _tar(self: _Extractor, fmt: ArchiveFormat, workers: int | Executor | None = None) -> None:
        """Read the tar stream and write every member that passes.

        A tar is one stream read in order, so `workers` and a password are
        ignored with a warning.

        Args:
            fmt: `TAR_GZ` or `TAR_ZST`.
            workers: Ignored.
        """
        if workers is not None:
            log.warning(
                "extract_archive: %s is one stream read in order, so workers was ignored -- it changed "
                "nothing and this ran on the calling thread. Only ZIP can use it.",
                fmt.value,
            )

        if self.password is not None:
            log.warning(
                "extract_archive: %s has no encryption of its own, so the password given was not needed "
                "and was not used.",
                fmt.value,
            )

        raw: IO[bytes] | None = open(self.src, "rb") if fmt is ArchiveFormat.TAR_ZST else None
        stream: Any

        if raw is None:
            stream = gzip.open(self.src, "rb")
        elif backends.std_zstd is not None:
            stream = backends.std_zstd.ZstdFile(raw, "rb")
        else:
            if backends.zstandard is None:
                raw.close()
                msg = "extract_archive: tar.zst needs a zstd backend -- `_require_zstd` must pass before `_tar` runs"
                raise RuntimeError(msg)

            stream = backends.zstandard.ZstdDecompressor().stream_reader(raw, closefd=False)

        try:
            with tarfile.open(fileobj=stream, mode="r|") as tf:
                for info in tf:
                    m = _Member(
                        info.name.replace("\\", "/").rstrip("/"),
                        info,
                        info.size,
                        0,
                        "dir"
                        if info.isdir()
                        else "file"
                        if info.isfile()
                        else "symlink"
                        if info.issym()
                        else "hardlink"
                        if info.islnk()
                        else "other",
                        info.linkname or None,
                    )
                    if (target := self._admit(m)) is None:
                        continue

                    if m.kind != "file":
                        self._link(m, target)
                    elif (data := tf.extractfile(info)) is not None:
                        self._spill(m, data, target)
        finally:
            try:
                stream.close()
            finally:
                if raw is not None:
                    raw.close()


__all__ = ("_TarMixin",)
