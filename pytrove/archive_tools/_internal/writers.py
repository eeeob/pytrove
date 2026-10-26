"""The two archive writers: zip, and compressed tar."""

from __future__ import annotations as _annotations

import gzip
import logging
import os
import tarfile
import zipfile
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

from ...enums import ArchiveFormat
from ...files_tools import ensure_path
from . import backends, stable

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from concurrent.futures import Executor

    from .common import _WalkEntry

log = logging.getLogger(__name__)


def _write_zip(
    entries: Iterable[_WalkEntry],
    out: IO[bytes],
    level: int,
    workers: int | None,
    executor: Executor | None,
    stability_retries: int,
    stability_check: Callable[[os.stat_result, str], bool],
) -> None:
    """Write walked entries into a zip: through fastzip on a pool, else `zipfile`.

    Directories get no record; extraction recreates them from member paths.
    fastzip's `write` only queues the read, so a guarded file's temp copy is
    removed after the whole archive is closed rather than straight away.

    Args:
        entries: The walk.
        out: The open destination.
        level: The deflate level, given to fastzip too.
        workers: A thread count.
        executor: A pool.
        stability_retries: How hard to guard against concurrent edits.
        stability_check: Which files are worth guarding.
    """
    use_fastzip = False
    # fastzip's `WZip.write` takes `archive_path`; a second name keeps that call off `ZipFile`'s signature,
    # since `ty` cannot tie `use_fastzip` to which writer `zf` holds.
    wzip: Any = None

    if (workers or 0) > 1 or executor is not None:
        if backends.WZip is None:
            log.warning(
                "compress_folder: workers requested but fastzip is not available, compressing on this thread "
                "instead. Install it with: pip install 'pytrove[archive]'"
            )
        else:
            use_fastzip = True

    if use_fastzip:
        name = getattr(out, "name", None)
        chooser = backends.fastzip_chooser
        zf = wzip = backends.WZip(
            Path(name if isinstance(name, (str, os.PathLike)) else "archive.zip"),
            fobj=out,
            threads=workers or None,
            executor=executor,
            # fastzip's own default rules (tiny files and nested zips stored), at the caller's level.
            chooser=chooser.CompressionChooser(
                default=f"deflate@compresslevel={level}", rules=chooser.DEFAULT_CHOOSER.rules
            ),
            force_zip64=True,
        )
    else:
        zf = zipfile.ZipFile(
            out,
            "w",
            zipfile.ZIP_DEFLATED,
            allowZip64=True,
            compresslevel=level,
            strict_timestamps=False,
        )

    pending_tmp: list[str] = []

    try:
        with zf:
            for path, arcname, is_dir in entries:
                if is_dir:
                    continue

                skip, tmp_path, before_stat = stable._stable_source(
                    path, stability_retries, stability_check
                )

                if skip:
                    continue

                try:
                    if use_fastzip:
                        # The write only queues the read, so no `_warn_if_changed` here: it would race that read.
                        if tmp_path is not None:
                            pending_tmp.append(tmp_path)

                        wzip.write(
                            ensure_path(tmp_path if tmp_path is not None else path),
                            archive_path=ensure_path(arcname),
                        )
                    elif tmp_path is not None:
                        zf.write(tmp_path, arcname)
                    else:
                        zf.write(path, arcname)
                        stable._warn_if_changed(path, before_stat)
                except OSError as exc:
                    log.warning("compress_folder: skipped %r (%s)", path, exc)
                finally:
                    if tmp_path is not None and not use_fastzip:
                        stable._discard_copies((tmp_path,))
    finally:
        stable._discard_copies(pending_tmp)


def _write_tar(
    entries: Iterable[_WalkEntry],
    out: IO[bytes],
    fmt: ArchiveFormat,
    level: int | None,
    workers: int | None,
    executor: Executor | None,
    stability_retries: int,
    stability_check: Callable[[os.stat_result, str], bool],
) -> None:
    """Write walked entries into one compressed tar stream.

    A tar is one stream, so a pool is ignored with a warning and a count goes
    to the zstd codec. Links are followed (`dereference=True`), as zip does,
    because a link member would be refused by `extract_archive` by default.

    Args:
        entries: The walk.
        out: The open destination.
        fmt: `TAR_GZ` or `TAR_ZST`.
        level: The codec level; 6 for gzip and 3 for zstd by default.
        workers: A thread count for zstd.
        executor: A pool, which a tar cannot use.
        stability_retries: How hard to guard against concurrent edits.
        stability_check: Which files are worth guarding.
    """
    if executor is not None:
        log.warning(
            "compress_folder: %s writes one stream and cannot use the executor passed as workers, so it was "
            "ignored and this ran on the calling thread. Pass a count instead to parallelise the codec on "
            "tar.zst, or use format='zip' to use the pool.",
            fmt.value,
        )

    compressor: Any

    if fmt is ArchiveFormat.TAR_ZST:
        level = 3 if level is None else level
        workers = 0 if not workers or workers <= 1 else workers

        if backends.std_zstd is None:
            if backends.zstandard is None:
                msg = "compress_folder: tar.zst needs a zstd backend -- `_require_zstd` must pass before `_write_tar` runs"
                raise RuntimeError(msg)

            compressor = backends.zstandard.ZstdCompressor(
                level=level, threads=workers
            ).stream_writer(out, closefd=False)
        else:
            zstd = backends.std_zstd
            compressor = zstd.ZstdFile(
                out,
                "wb",
                options={
                    zstd.CompressionParameter.compression_level: level,
                    zstd.CompressionParameter.nb_workers: workers,
                },
            )
    else:
        compressor = gzip.GzipFile(
            fileobj=out, mode="wb", compresslevel=6 if level is None else level
        )

    with compressor as stream, tarfile.open(fileobj=stream, mode="w|", dereference=True) as tf:
        for path, arcname, is_dir in entries:
            tmp_path = before_stat = None

            if not is_dir:
                skip, tmp_path, before_stat = stable._stable_source(
                    path, stability_retries, stability_check
                )

                if skip:
                    continue

            try:
                tf.add(tmp_path if tmp_path is not None else path, arcname=arcname, recursive=False)

                if tmp_path is None and not is_dir:
                    stable._warn_if_changed(path, before_stat)
            except OSError as exc:
                log.warning("compress_folder: skipped %r (%s)", path, exc)
            finally:
                if tmp_path is not None:
                    stable._discard_copies((tmp_path,))


__all__ = (
    "_write_tar",
    "_write_zip",
)
