from __future__ import annotations as _annotations

import contextlib
import importlib.util
import io
import os
import stat
import sys
import tarfile
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import ModuleType, SimpleNamespace
from typing import Any, NoReturn, cast

import pytest

from pytrove.archive_tools._internal import (
    backends,
    common,
    compressor,
    limiter,
    members,
    placement,
    stable,
    writers,
    zipread,
)
from pytrove.archive_tools._internal import extractor as extractor_module
from pytrove.archive_tools._internal.extractor import _Extractor
from pytrove.archive_tools._internal.rules import _Filter, _Rules
from pytrove.enums import (
    ArchiveDuplicatePolicy,
    ArchiveFormat,
    ArchiveLinkPolicy,
    ArchiveOverwritePolicy,
)
from pytrove.errors import ArchiveLimitError, ArchivePolicyError, ValidationError
from pytrove.typings import ArchiveLimits


class _Entry:
    """A stand-in for `os.DirEntry`, with only a name."""

    def __init__(self, name: str) -> None:
        """Store `name`."""
        self.name = name

    def stat(self) -> Any:
        """Fail like an unreadable entry."""
        raise OSError


def test_constants() -> None:
    assert common._LINK_MAX == 4096
    assert common._NT is (os.name == "nt")
    assert dict(common._SUFFIXES)[".tgz"] is ArchiveFormat.TAR_GZ


@pytest.mark.parametrize(
    ("name", "fmt"),
    [
        ("a.ZIP", ArchiveFormat.ZIP),
        ("a.tar.zst", ArchiveFormat.TAR_ZST),
        ("a.tar.gz", ArchiveFormat.TAR_GZ),
        ("a.tgz", ArchiveFormat.TAR_GZ),
        ("a.rar", None),
    ],
)
def test_format_from_suffix(name: str, fmt: ArchiveFormat | None) -> None:
    assert common._format_from_suffix(name) is fmt


def test_split_workers_reads_a_count_or_a_pool() -> None:
    assert common._split_workers(None, "x") == (None, None)
    assert common._split_workers(3, "x") == (3, None)
    assert common._split_workers(-1, "x") == (os.cpu_count() or 1, None)

    with ThreadPoolExecutor(1) as pool:
        assert common._split_workers(pool, "x") == (None, pool)

    with pytest.raises(ValidationError, match="who: workers"):
        common._split_workers(True, "who")


def test_is_hidden_reads_the_name_and_survives_an_unreadable_entry() -> None:
    assert common._is_hidden("x", _Entry(".git"))
    assert not common._is_hidden("x", _Entry("src"))
    assert not common._is_hidden("x", None)


def test_temp_file_rule_matches_only_the_temp_file_in_its_folder() -> None:
    rule = common._temp_file_rule("out/", ".b.zip.")
    assert rule("out/.b.zip.abc123.tmp", None)
    assert not rule("other/.b.zip.abc123.tmp", None)
    assert not rule("out/.b.zip.notes", None)
    assert not rule("out/deep/.b.zip.x.tmp", None)


def test_require_zstd_raises_without_any_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends, "std_zstd", None)
    monkeypatch.setattr(backends, "zstandard", None)

    with pytest.raises(ImportError):
        common._require_zstd()


def test_require_zstd_passes_with_a_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends, "zstandard", object())
    assert common._require_zstd() is None


def test_backends_expose_every_name() -> None:
    assert set(backends.__all__) == {
        "GitIgnoreSpec",
        "PathSpec",
        "WZip",
        "fastzip_chooser",
        "std_zstd",
        "zstandard",
    }


def test_stable_source_reads_directly_when_not_guarded(tmp_path: Path) -> None:
    target = tmp_path / "f"
    target.write_bytes(b"x")
    skip, tmp, before = stable._stable_source(str(target), 0, lambda st, p: True)
    assert (skip, tmp) == (False, None)
    assert before.st_size == 1


def test_stable_source_copies_a_guarded_file(tmp_path: Path) -> None:
    target = tmp_path / "f"
    target.write_bytes(b"data")
    skip, tmp, _ = stable._stable_source(str(target), 2, lambda st, p: True)

    try:
        assert skip is False
        assert Path(tmp).read_bytes() == b"data"
    finally:
        os.unlink(tmp)


def test_stable_source_skips_a_file_that_cannot_be_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f"
    target.write_bytes(b"x")

    def boom(path: str, retries: int) -> Any:
        """Fail like a vanished file."""
        raise OSError

    monkeypatch.setattr(stable, "_read_stable", boom)
    assert stable._stable_source(str(target), 1, lambda st, p: True)[:2] == (True, None)


def test_stable_source_of_a_missing_file_is_read_directly(tmp_path: Path) -> None:
    assert stable._stable_source(str(tmp_path / "gone"), 3, lambda st, p: True) == (
        False,
        None,
        None,
    )


def test_read_stable_refuses_a_negative_retry_count(tmp_path: Path) -> None:
    target = tmp_path / "f"
    target.write_bytes(b"x")

    with pytest.raises(ValueError, match="retries must be at least 0"):
        stable._read_stable(str(target), -1)


def test_tar_reader_refuses_tar_zst_without_a_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "a.tar.zst"
    src.write_bytes(b"")
    monkeypatch.setattr(backends, "std_zstd", None)
    monkeypatch.setattr(backends, "zstandard", None)
    extractor = _Extractor(src, tmp_path / "out", _Filter.from_rules((), ()))

    with pytest.raises(RuntimeError, match="needs a zstd backend"):
        extractor._tar(ArchiveFormat.TAR_ZST)


def test_tar_writer_refuses_tar_zst_without_a_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends, "std_zstd", None)
    monkeypatch.setattr(backends, "zstandard", None)

    with pytest.raises(RuntimeError, match="needs a zstd backend"):
        writers._write_tar(
            (), io.BytesIO(), ArchiveFormat.TAR_ZST, None, None, None, 0, lambda st, p: False
        )


# --- shared helpers for the gap tests below --------------------------------


def _ready_extractor(tmp_path: Path, limits: ArchiveLimits | None = None) -> _Extractor:
    """An `_Extractor` set up as `run` leaves it, writing straight into `dest`."""
    limits = ArchiveLimits() if limits is None else limits
    dest = tmp_path / "dest"
    dest.mkdir(exist_ok=True)
    extractor = _Extractor(tmp_path / "a.zip", dest, _Filter.from_rules((), ()), limits)
    extractor._root = dest
    extractor._limiter = limiter._Limiter(limits, extractor.src)
    return extractor


def _scandir_failing_at(monkeypatch: pytest.MonkeyPatch, module: ModuleType, name: str) -> None:
    """Make `os.scandir`, as `module` sees it, fail for the directory called `name`."""
    real = os.scandir

    def scandir(path: str | os.PathLike[str]) -> Any:
        """Refuse `name`, list everything else."""
        if Path(path).name == name:
            msg = "denied"
            raise PermissionError(msg)

        return real(path)

    monkeypatch.setattr(module.os, "scandir", scandir)


class _HiddenEntry:
    """A visible-named entry whose `stat` reports the Windows hidden attribute."""

    name = "visible"

    def stat(self) -> Any:
        """Report the hidden attribute."""
        return SimpleNamespace(st_file_attributes=stat.FILE_ATTRIBUTE_HIDDEN)


# --- backends --------------------------------------------------------------


def test_backends_fall_back_to_none_when_nothing_is_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for blocked in ("compression", "zstandard", "pathspec", "fastzip", "fastzip.write"):
        monkeypatch.setitem(sys.modules, blocked, None)

    spec = importlib.util.spec_from_file_location(
        # Named inside the package, so its relative import of `pytrove._internal` resolves.
        "pytrove.archive_tools._internal._backends_probe",
        backends.__file__,
    )
    assert spec is not None
    assert spec.loader is not None
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    assert (probe.std_zstd, probe.zstandard, probe.WZip, probe.PathSpec, probe.GitIgnoreSpec) == (
        None,
    ) * 5


# --- common ----------------------------------------------------------------


def test_is_hidden_reads_the_windows_attribute_only_where_stat_reports_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(common, "_HAS_FILE_ATTRIBUTES", True)
    assert common._is_hidden("x", cast("os.DirEntry", _HiddenEntry()))

    monkeypatch.setattr(common, "_HAS_FILE_ATTRIBUTES", False)
    assert not common._is_hidden("x", cast("os.DirEntry", _HiddenEntry()))


@pytest.mark.parametrize(
    ("version", "cure"),
    [
        ((3, 14), "pip install zstandard"),
        ((3, 13), r"pip install -U 'pytrove\[archive\]'"),
    ],
)
def test_require_zstd_names_the_cure_for_the_running_version(
    monkeypatch: pytest.MonkeyPatch,
    version: tuple[int, int],
    cure: str,
) -> None:
    monkeypatch.setattr(backends, "std_zstd", None)
    monkeypatch.setattr(backends, "zstandard", None)
    monkeypatch.setattr(common, "sys", SimpleNamespace(version_info=version))

    with pytest.raises(ImportError, match=cure):
        common._require_zstd()


# --- compressor ------------------------------------------------------------


def test_compressor_logs_and_skips_a_directory_it_cannot_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "in.txt").write_text("x")
    (tmp_path / "top.txt").write_text("x")
    _scandir_failing_at(monkeypatch, compressor, "sub")

    walked = list(compressor._Compressor(str(tmp_path), _Filter.from_rules((), ())))

    assert walked == [(str(tmp_path / "top.txt"), "top.txt", False)]
    assert "cannot read directory" in caplog.text


def test_compressor_follows_a_link_to_a_file_inside_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "d").mkdir()
    link = tmp_path / "d" / "link.txt"
    link.write_text("x")
    # A real file stands in for the link: it resolves to itself, a file inside the root.
    # `_HAS_FILE_ATTRIBUTES` makes the walk ask `_is_link` beyond `DirEntry.is_symlink()`.
    monkeypatch.setattr(compressor, "_HAS_FILE_ATTRIBUTES", True)
    monkeypatch.setattr(compressor, "_is_link", lambda path: Path(path).name == "link.txt")

    walked = list(
        compressor._Compressor(str(tmp_path), _Filter.from_rules((), ()), follow_links=True)
    )

    assert walked == [(str(tmp_path / "d"), "d", True), (str(link), "d/link.txt", False)]


def test_compressor_drops_a_followed_link_the_filter_excludes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    (tmp_path / "link.txt").write_text("x")
    monkeypatch.setattr(compressor, "_HAS_FILE_ATTRIBUTES", True)
    monkeypatch.setattr(compressor, "_is_link", lambda path: Path(path).name == "link.txt")

    flt = _Filter.from_rules((), ["link.txt"])

    assert list(compressor._Compressor(str(tmp_path), flt, follow_links=True)) == []
    assert caplog.text == ""


def test_compressor_leaves_out_an_entry_whose_type_cannot_be_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    real = tmp_path / "f.txt"
    real.write_text("x")

    class _UnreadableEntry:
        """A real file whose type query fails."""

        path = str(real)
        name = "f.txt"

        def is_symlink(self) -> bool:
            """Not a link."""
            return False

        def is_dir(self, *, follow_symlinks: bool = True) -> bool:
            """Fail like an entry removed mid-walk."""
            msg = "gone"
            raise OSError(msg)

        is_file = is_dir

    monkeypatch.setattr(
        compressor.os, "scandir", lambda path: contextlib.nullcontext([_UnreadableEntry()])
    )

    assert list(compressor._Compressor(str(tmp_path), _Filter.from_rules((), ()))) == []
    assert "cannot read the type" in caplog.text


# --- extractor -------------------------------------------------------------


def test_inspect_logs_a_directory_it_cannot_read_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    extractor = _ready_extractor(tmp_path, ArchiveLimits(dir_check=lambda path: True))
    _scandir_failing_at(monkeypatch, extractor_module, "dest")

    extractor._inspect(extractor._root)

    assert "cannot read back" in caplog.text


def test_detect_format_falls_back_to_the_name_when_the_file_cannot_be_opened(
    tmp_path: Path,
) -> None:
    assert _Extractor.detect_format(str(tmp_path / "missing.zip")) is ArchiveFormat.ZIP


def test_detect_format_falls_back_to_the_name_when_the_content_says_nothing(tmp_path: Path) -> None:
    src = tmp_path / "junk.tgz"
    src.write_bytes(b"not an archive")

    assert _Extractor.detect_format(str(src)) is ArchiveFormat.TAR_GZ


# --- limiter ---------------------------------------------------------------


def test_grew_stops_a_member_that_outgrows_max_file_size(tmp_path: Path) -> None:
    lim = limiter._Limiter(ArchiveLimits(max_file_size=4), tmp_path / "a.zip")
    lim.grew("m", 4)

    with pytest.raises(ArchiveLimitError, match="'m' has written 5 bytes, over the 4 allowed"):
        lim.grew("m", 5)


def test_grew_without_max_file_size_never_stops(tmp_path: Path) -> None:
    limiter._Limiter(ArchiveLimits(), tmp_path / "a.zip").grew("m", 1 << 40)


def test_allows_dir_without_dir_check_keeps_everything(tmp_path: Path) -> None:
    assert limiter._Limiter(ArchiveLimits(), tmp_path / "a.zip").allows_dir(tmp_path)


# --- members ---------------------------------------------------------------


def _member(name: str, kind: Any, size: int = 0, target: str | None = None) -> limiter._Member:
    """A zip member as `_zip` builds one."""
    return limiter._Member(name, zipfile.ZipInfo(name), size, size, kind, target)


def test_mkdir_records_each_level_it_creates_for_cleanup(tmp_path: Path) -> None:
    extractor = _ready_extractor(tmp_path)
    extractor._built = []
    deep = extractor._root / "a" / "b"

    extractor._mkdir(deep)

    assert deep.is_dir()
    assert extractor._built == [extractor._root / "a", deep]


def test_link_refuses_a_hardlink_that_resolves_outside(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    extractor = _ready_extractor(tmp_path, ArchiveLimits(hardlinks="allow"))
    target = extractor._root / "h.txt"

    extractor._link(_member("h.txt", "hardlink", target="../outside"), target)

    assert not target.exists()
    assert "pointing outside" in caplog.text


@pytest.mark.parametrize("built", [None, []])
def test_link_creates_a_hardlink_and_records_it_only_for_cleanup(
    tmp_path: Path, built: list[Path] | None
) -> None:
    extractor = _ready_extractor(tmp_path, ArchiveLimits(hardlinks="allow"))
    extractor._built = built
    (extractor._root / "real.txt").write_text("data")
    target = extractor._root / "h.txt"

    extractor._link(_member("h.txt", "hardlink", target="real.txt"), target)

    assert os.path.samefile(target, extractor._root / "real.txt")
    assert extractor._built == (None if built is None else [target])


def test_link_never_replaces_a_directory(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    extractor = _ready_extractor(tmp_path, ArchiveLimits(hardlinks="allow"))
    (extractor._root / "real.txt").write_text("data")
    target = extractor._root / "taken"
    target.mkdir()

    extractor._link(_member("taken", "hardlink", target="real.txt"), target)

    assert target.is_dir()
    assert "a directory stands at" in caplog.text


def test_link_removes_its_temp_link_when_it_cannot_be_moved_into_place(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    extractor = _ready_extractor(tmp_path, ArchiveLimits(hardlinks="allow"))
    (extractor._root / "real.txt").write_text("data")
    target = extractor._root / "h.txt"

    def refuse(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        """Fail like a locked target."""
        msg = "locked"
        raise OSError(msg)

    monkeypatch.setattr(members.os, "replace", refuse)

    extractor._link(_member("h.txt", "hardlink", target="real.txt"), target)
    monkeypatch.undo()

    assert sorted(p.name for p in extractor._root.iterdir()) == ["real.txt"]
    assert "could not put hardlink" in caplog.text


def test_spill_logs_a_member_that_produces_less_than_it_declares(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    extractor = _ready_extractor(tmp_path)
    target = extractor._root / "m.txt"

    extractor._spill(_member("m.txt", "file", size=10), io.BytesIO(b"abc"), target)

    assert target.read_bytes() == b"abc"
    assert "declares 10 bytes but produced 3" in caplog.text


# --- placement -------------------------------------------------------------


@pytest.mark.parametrize(("nt", "expected"), [(True, ("a", "b")), (False, ("a. ", "b"))])
def test_under_strips_trailing_dots_and_spaces_only_under_windows_rules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    nt: bool,
    expected: tuple[str, str],
) -> None:
    monkeypatch.setattr(placement, "_NT", nt)
    extractor = _ready_extractor(tmp_path)

    assert extractor._under("a. /b") == extractor._root.joinpath(*expected)


def test_under_refuses_a_name_windows_rules_strip_to_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(placement, "_NT", True)

    assert _ready_extractor(tmp_path)._under(".") is None


def test_place_gives_back_the_name_of_a_member_resolving_outside(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    extractor = _ready_extractor(tmp_path)
    extractor._cleared["sub"] = None  # As if `sub` were a junction leading out.

    assert extractor._place(_member("sub/x", "file", size=1)) is None
    assert "sub/x" not in extractor._limiter._seen
    assert extractor._limiter.files == 0
    assert "resolves outside the destination" in caplog.text


# --- rules -----------------------------------------------------------------


@pytest.mark.parametrize(("rule", "shown"), [(42, "42"), ("", "''")])
@pytest.mark.parametrize("who", ["compress_folder", "extract_archive"])
def test_from_rules_refuses_what_is_neither_a_pattern_nor_a_callable(
    rule: Any, shown: str, who: str
) -> None:
    with pytest.raises(ValidationError, match=f"^{who}: {shown} is not a pattern or a callable$"):
        _Filter.from_rules([rule], (), who)


def test_a_predicate_that_raises_is_named_with_the_original_as_cause() -> None:
    def reads_the_name(rel: str, raw: Any) -> bool:
        """Assume a `DirEntry`."""
        return raw.name == rel

    flt = _Filter.from_rules([reads_the_name], (), "extract_archive")

    with pytest.raises(
        ValidationError, match="^extract_archive: the rule 'reads_the_name' raised AttributeError"
    ) as info:
        flt.matches("a.txt")

    assert isinstance(info.value.__cause__, AttributeError)


def test_an_include_predicate_keeps_what_it_accepts_and_nothing_else() -> None:
    flt = _Filter.from_rules([lambda rel, raw: rel == "keep"], ())

    assert flt.matches("keep")
    assert not flt.matches("other")


def test_an_exclude_name_drops_that_name_at_any_depth() -> None:
    flt = _Filter.from_rules((), ["skip.txt"])

    assert not flt.matches("a/b/skip.txt")
    assert flt.matches("a/b/keep.txt")


# --- stable ----------------------------------------------------------------


def _record_temp_files(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Collect every temp path `_read_stable` creates."""
    made: list[str] = []
    real = tempfile.mkstemp

    def mkstemp(*args: Any, **kwargs: Any) -> tuple[int, str]:
        """Create, and remember, one temp file."""
        fd, name = real(*args, **kwargs)
        made.append(name)
        return fd, name

    monkeypatch.setattr(stable.tempfile, "mkstemp", mkstemp)
    return made


def _fail_copy(src: str, dst: str) -> None:
    """Fail like a file that vanished mid-read."""
    msg = "copy failed"
    raise OSError(msg)


def test_read_stable_removes_its_temp_file_when_the_copy_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "f").write_bytes(b"x")
    made = _record_temp_files(monkeypatch)
    monkeypatch.setattr(stable.shutil, "copyfile", _fail_copy)

    with pytest.raises(OSError, match="copy failed"):
        stable._read_stable(str(tmp_path / "f"), 0)

    assert len(made) == 1
    assert not os.path.exists(made[0])


def test_read_stable_raises_the_copy_error_even_if_the_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "f").write_bytes(b"x")
    made = _record_temp_files(monkeypatch)
    monkeypatch.setattr(stable.shutil, "copyfile", _fail_copy)

    def refuse(path: str) -> None:
        """Fail like a temp file another process holds open."""
        msg = "unlink failed"
        raise OSError(msg)

    monkeypatch.setattr(stable.os, "unlink", refuse)

    try:
        with pytest.raises(OSError, match="copy failed"):
            stable._read_stable(str(tmp_path / "f"), 0)
    finally:
        monkeypatch.undo()

    assert os.path.exists(made[0])
    os.unlink(made[0])


# --- tarread ---------------------------------------------------------------


def test_tar_reader_skips_a_file_member_it_gets_no_data_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extractor = _ready_extractor(tmp_path)
    extractor.src = tmp_path / "a.tar.gz"

    with tarfile.open(extractor.src, "w:gz") as tf:
        info = tarfile.TarInfo("f.txt")
        info.size = 1
        tf.addfile(info, io.BytesIO(b"x"))

    monkeypatch.setattr(tarfile.TarFile, "extractfile", lambda self, member: None)

    extractor._tar(ArchiveFormat.TAR_GZ)

    assert list(extractor._root.iterdir()) == []


# --- writers ---------------------------------------------------------------


def _two_files(tmp_path: Path) -> list[tuple[str, str, bool]]:
    """Walk entries for a directory and two files under it."""
    (tmp_path / "d").mkdir()

    for name in ("a", "b"):
        (tmp_path / "d" / name).write_text(name)

    return [(str(tmp_path / "d"), "d", True)] + [
        (str(tmp_path / "d" / n), f"d/{n}", False) for n in ("a", "b")
    ]


def _members_of(data: bytes, fmt: ArchiveFormat) -> list[str]:
    """List the file members of a zip or tar.gz held in memory."""
    if fmt is ArchiveFormat.ZIP:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.namelist()

    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        return [m.name for m in tf.getmembers() if m.isfile()]


@pytest.mark.parametrize("fmt", [ArchiveFormat.ZIP, ArchiveFormat.TAR_GZ])
def test_writers_leave_out_a_file_the_stability_guard_skips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fmt: ArchiveFormat,
) -> None:
    entries = _two_files(tmp_path)
    real = stable._stable_source

    def skip_a(
        path: str, retries: int, check: Any
    ) -> tuple[bool, str | None, os.stat_result | None]:
        """Skip `a` as an unreadable file would be, read the rest directly."""
        return (True, None, None) if path.endswith("a") else real(path, retries, check)

    monkeypatch.setattr(stable, "_stable_source", skip_a)
    out = io.BytesIO()

    if fmt is ArchiveFormat.ZIP:
        writers._write_zip(entries, out, 6, None, None, 0, lambda st, p: False)
    else:
        writers._write_tar(entries, out, fmt, None, None, None, 0, lambda st, p: False)

    assert _members_of(out.getvalue(), fmt) == ["d/b"]


def test_tar_writer_logs_and_skips_a_file_it_cannot_add(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "real").write_text("x")
    entries = [(str(tmp_path / "gone"), "gone", False), (str(tmp_path / "real"), "real", False)]
    out = io.BytesIO()

    writers._write_tar(entries, out, ArchiveFormat.TAR_GZ, None, None, None, 0, lambda st, p: False)

    assert _members_of(out.getvalue(), ArchiveFormat.TAR_GZ) == ["real"]
    assert "skipped" in caplog.text


class _FakeWZip:
    """Records what `_write_zip` hands fastzip's `WZip`."""

    made: list[_FakeWZip] = []  # A per-test record, reset by `fake_wzip`.

    def __init__(
        self,
        path: Path,
        *,
        fobj: Any,
        threads: int | None,
        executor: Any,
        chooser: Any,
        force_zip64: bool,
    ) -> None:
        """Record the constructor arguments."""
        self.args = (path, fobj, threads, executor, force_zip64)
        self.chooser = chooser
        self.written: list[tuple[Path, Path]] = []
        self.alive_at_close: list[bool] = []
        _FakeWZip.made.append(self)

    def __enter__(self) -> _FakeWZip:  # noqa: PYI034 - a test double that is never subclassed
        """Open."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close, noting whether each queued file still exists for the deferred read."""
        self.alive_at_close = [path.exists() for path, _ in self.written]

    def write(self, path: Path, *, archive_path: Path) -> None:
        """Queue one file."""
        self.written.append((path, archive_path))


@pytest.fixture
def fake_wzip(monkeypatch: pytest.MonkeyPatch) -> type[_FakeWZip]:
    """Put `_FakeWZip` where fastzip's writer would be, with a chooser module that records its arguments."""
    _FakeWZip.made = []
    monkeypatch.setattr(backends, "WZip", _FakeWZip)
    monkeypatch.setattr(
        backends,
        "fastzip_chooser",
        SimpleNamespace(
            CompressionChooser=lambda default, rules: SimpleNamespace(default=default, rules=rules),
            DEFAULT_CHOOSER=SimpleNamespace(rules=["store tiny files"]),
        ),
    )
    return _FakeWZip


def test_zip_writer_queues_files_on_fastzip_when_given_workers(
    tmp_path: Path, fake_wzip: type[_FakeWZip]
) -> None:
    out = io.BytesIO()

    writers._write_zip(_two_files(tmp_path), out, 6, 4, None, 0, lambda st, p: False)

    (wzip,) = fake_wzip.made
    assert wzip.args == (Path("archive.zip"), out, 4, None, True)
    assert wzip.chooser.default == "deflate@compresslevel=6"
    assert wzip.written == [
        (tmp_path / "d" / "a", Path("d/a")),
        (tmp_path / "d" / "b", Path("d/b")),
    ]


@pytest.mark.parametrize("level", [-1, 0, 1, 9])
def test_zip_writer_gives_fastzip_the_level_with_its_default_rules(
    tmp_path: Path, fake_wzip: type[_FakeWZip], level: int
) -> None:
    writers._write_zip(_two_files(tmp_path), io.BytesIO(), level, 4, None, 0, lambda st, p: False)

    (wzip,) = fake_wzip.made
    assert wzip.chooser.default == f"deflate@compresslevel={level}"
    assert wzip.chooser.rules == ["store tiny files"]


def test_zip_writer_names_fastzip_after_the_open_file(
    tmp_path: Path, fake_wzip: type[_FakeWZip]
) -> None:
    with ThreadPoolExecutor(1) as pool, open(tmp_path / "out.zip", "wb") as out:
        writers._write_zip(_two_files(tmp_path), out, 6, None, pool, 0, lambda st, p: False)

    assert fake_wzip.made[0].args[0] == tmp_path / "out.zip"


def test_zip_writer_keeps_fastzip_temp_copies_until_the_archive_is_closed(
    tmp_path: Path,
    fake_wzip: type[_FakeWZip],
) -> None:
    writers._write_zip(_two_files(tmp_path), io.BytesIO(), 6, 4, None, 1, lambda st, p: True)

    (wzip,) = fake_wzip.made
    copies = [path for path, _ in wzip.written]
    assert [arc for _, arc in wzip.written] == [Path("d/a"), Path("d/b")]
    assert all(path.parent != tmp_path / "d" for path in copies)
    assert wzip.alive_at_close == [True, True]
    assert not any(path.exists() for path in copies)


# --- zipread ---------------------------------------------------------------


def _zip_with(path: Path, *entries: tuple[zipfile.ZipInfo | str, bytes]) -> Path:
    """Write a zip holding `entries`."""
    with zipfile.ZipFile(path, "w") as zf:
        for info, data in entries:
            zf.writestr(info, data)

    return path


def _symlink_info(name: str) -> zipfile.ZipInfo:
    """A zip header marking `name` as a symlink."""
    info = zipfile.ZipInfo(name)
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return info


class _Unclosable:
    """A handle whose `close` fails."""

    def close(self) -> None:
        """Fail like a handle on a vanished share."""
        msg = "gone"
        raise OSError(msg)


def test_zip_readers_close_every_handle_even_when_one_fails(tmp_path: Path) -> None:
    readers = zipread._ZipReaders(_zip_with(tmp_path / "a.zip", ("f", b"x")), None)
    handle = readers.get()
    readers._all.insert(0, cast("zipfile.ZipFile", _Unclosable()))

    readers.close()

    assert handle.fp is None
    assert readers._all == []


def test_zip_copy_refuses_winzip_aes(tmp_path: Path) -> None:
    extractor = _ready_extractor(tmp_path)
    info = zipfile.ZipInfo("f")
    info.compress_type = 99

    with pytest.raises(ValidationError, match="uses WinZip AES encryption"):
        extractor._zip_copy(
            zipread._ZipReaders(extractor.src, None),
            limiter._Member("f", info, 1, 1, "file"),
            tmp_path,
        )


@pytest.fixture
def recorded_links(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str | None, Path]]:
    """Replace `_Extractor._link` with a recorder of `(link destination, target)`."""
    calls: list[tuple[str | None, Path]] = []
    monkeypatch.setattr(
        _Extractor, "_link", lambda self, m, target: calls.append((m.target, target))
    )
    return calls


def _copy_link(tmp_path: Path, extractor: _Extractor, destination: bytes) -> Path:
    """Put one zip symlink member pointing at `destination` through `_zip_copy`."""
    src = _zip_with(tmp_path / "links.zip", (_symlink_info("ln"), destination))
    readers = zipread._ZipReaders(src, None)
    target = extractor._root / "ln"

    try:
        info = readers.get().getinfo("ln")
        extractor._zip_copy(
            readers,
            limiter._Member("ln", info, info.file_size, info.compress_size, "symlink"),
            target,
        )
    finally:
        readers.close()

    return target


def test_zip_copy_hands_a_link_its_decoded_destination(
    tmp_path: Path,
    recorded_links: list[tuple[str | None, Path]],
) -> None:
    extractor = _ready_extractor(tmp_path)

    target = _copy_link(tmp_path, extractor, b"real.txt")

    assert recorded_links == [("real.txt", target)]


def test_zip_copy_refuses_a_link_destination_longer_than_any_path(
    tmp_path: Path,
    recorded_links: list[tuple[str | None, Path]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _copy_link(tmp_path, _ready_extractor(tmp_path), b"x" * (common._LINK_MAX + 1))

    assert recorded_links == []
    assert "longer than 4096 bytes" in caplog.text


def test_zip_copy_logs_a_link_destination_it_cannot_read(
    tmp_path: Path,
    recorded_links: list[tuple[str | None, Path]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _BrokenData(io.BytesIO):
        """Member data whose read fails."""

        def read(self, size: int | None = -1) -> bytes:
            """Fail like a damaged member."""
            msg = "crc"
            raise OSError(msg)

    class _Readers:
        """Hands out a handle whose members cannot be read."""

        def get(self) -> Any:
            """Return the handle."""
            return SimpleNamespace(open=lambda info: _BrokenData())

    extractor = _ready_extractor(tmp_path)
    member = limiter._Member("ln", _symlink_info("ln"), 8, 8, "symlink")

    extractor._zip_copy(cast("zipread._ZipReaders", _Readers()), member, extractor._root / "ln")

    assert recorded_links == []
    assert "could not read the destination of symlink" in caplog.text


def test_zip_on_a_pool_keeps_a_bounded_number_of_writes_in_flight(tmp_path: Path) -> None:
    names = [f"f{i:02}.txt" for i in range(30)]
    extractor = _ready_extractor(tmp_path)
    extractor.src = _zip_with(tmp_path / "many.zip", *((name, name.encode()) for name in names))

    extractor._zip(2)

    assert sorted(p.name for p in extractor._root.iterdir()) == names
    assert all((extractor._root / name).read_bytes() == name.encode() for name in names)


@pytest.mark.skipif(os.name != "nt", reason="needs `os.path.normcase` to fold case, as on Windows")
def test_zip_on_a_pool_serialises_two_members_landing_on_one_path(tmp_path: Path) -> None:
    extractor = _ready_extractor(tmp_path, ArchiveLimits(overwrite="overwrite"))
    extractor.src = _zip_with(
        tmp_path / "case.zip", ("same.txt", b"first"), ("SAME.TXT", b"second")
    )

    extractor._zip(2)

    assert (extractor._root / "same.txt").read_bytes() == b"second"


def _safe_target(dest: Path, name: str, cache: dict[str, Path | None] | None = None) -> Path | None:
    """Where `name` resolves to, for a bare destination and no rules.

    Working out a member's path is not a method of its own any more -- it
    lives inside _Extractor._place, which reads the extraction's root and
    its directory cache -- so a synthetic directory member is put through
    _place instead. A directory skips the `overwrite` policy, so what comes
    back is the resolved path or None, which is what these tests are about.

    A fresh extractor per call is what a test wants anyway, since the cache
    is what several of them are about.
    """

    e = _Extractor(dest, dest, _Filter.from_rules((), ()))
    e._root = dest
    e._limiter = limiter._Limiter(ArchiveLimits(), dest)

    if cache is not None:
        e._cleared = cache

    return e._place(limiter._Member(name, None, 0, 0, "dir"))


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "../../escape.txt",
        "a/../../escape.txt",
        "..\\escape.txt",
        "",
    ],
)
def test_safe_target_refuses_traversal(tmp_path: Path, name: str) -> None:
    dest = tmp_path / "dest"
    dest.mkdir()
    assert _safe_target(dest, name) is None


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "../../escape.txt",
        "a/../../escape.txt",
        "..\\escape.txt",
        "",
        "/",
        "///",
        "C:/Windows/x",
        "c:x",
        "sub/../../escape.txt",
        "pkg/a.py",
        "a/../b.txt",
        "sub/./a.txt",
        "/etc/passwd",
        "plain.txt",
    ],
)
def test_the_directory_cache_never_changes_the_verdict(tmp_path: Path, name: str) -> None:
    # _safe_target resolves the directory part once and reuses it for
    # siblings. That is only sound if it decides exactly what the
    # per-member resolve decided.
    dest = tmp_path / "dest"
    dest.mkdir()

    assert _safe_target(dest, name, {}) == _safe_target(dest, name)


@pytest.mark.parametrize(
    "name",
    [
        "/etc/passwd",
        "C:/Windows/x",
        "c:x",
        "//server/share/x",
        "/",
    ],
)
def test_absolute_names_are_refused_outright(tmp_path: Path, name: str) -> None:
    # tar strips the leading separator and keeps such a member. This does
    # not: rewriting where the archive asked to go is a silent repair, and
    # an archive that asks to write outside the directory it was handed has
    # not earned the benefit of the doubt on its other names either.
    dest = tmp_path / "dest"
    dest.mkdir()

    assert _safe_target(dest, name) is None


@pytest.mark.parametrize(
    "name",
    [
        "/etc/passwd",
        "C:/Windows/x",
        "c:x",
        "//server/share/x",
        "/",
        "///",
    ],
)
def test_an_absolute_member_name_is_refused_not_repaired(tmp_path: Path, name: str) -> None:
    # tar strips the leading separator and keeps the member. This does not:
    # rewriting where the archive asked to go is a silent repair, and an
    # archive asking to write outside its destination has not earned the
    # benefit of the doubt on its other names either.
    dest = tmp_path / "dest"
    dest.mkdir()

    assert _safe_target(dest, name) is None


def test_a_member_the_policy_refuses_is_never_counted() -> None:
    # Directly, because through an extraction the tallies are only visible
    # by what they refuse. `overwrite` is asked first, so a member it turns
    # away leaves every tally exactly where it was.
    dest = Path("dest")
    lim = limiter._Limiter(ArchiveLimits(overwrite="skip", max_dir_entries=10), Path("a.zip"))

    assert lim.allows_target("sub/a.txt", dest / "sub" / "a.txt") is True
    assert lim.allows_target("sub/a.txt", dest / "sub" / "a.txt") is False

    # Nothing was spent on the second: no bytes, no entry, no breadth.
    assert (lim.files, lim.total, lim._breadth, lim._counted) == (0, 0, {}, set())


class _FakeStat:
    def __init__(
        self,
        st_size: int,
        st_mtime_ns: int,
        st_ctime_ns: int = 0,
        st_atime_ns: int = 0,
        st_mode: int = 0o644,
    ) -> None:
        self.st_size = st_size
        self.st_mtime_ns = st_mtime_ns
        self.st_ctime_ns = st_ctime_ns
        self.st_atime_ns = st_atime_ns
        self.st_mode = st_mode


def test_same_stat_compares_size_mtime_and_ctime() -> None:
    base = _FakeStat(1, 1, 1)

    assert stable._same_stat(base, _FakeStat(1, 1, 1)) is True
    assert stable._same_stat(base, _FakeStat(2, 1, 1)) is False
    assert stable._same_stat(base, _FakeStat(1, 2, 1)) is False
    assert stable._same_stat(base, _FakeStat(1, 1, 2)) is False


def test_read_stable_settles_on_the_first_attempt_when_nothing_changes(tmp_path: Path) -> None:
    target = tmp_path / "f.bin"
    content = b"hello world" * 100
    target.write_bytes(content)

    tmp, st, settled = stable._read_stable(str(target), retries=3)
    try:
        assert settled is True
        assert st.st_size == len(content)
        assert Path(tmp).read_bytes() == content
    finally:
        os.unlink(tmp)


def test_read_stable_retries_until_two_stats_agree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f.bin"
    target.write_bytes(b"x")

    # shutil.copyfile is stubbed out here so the only os.stat(target) calls
    # left are _read_stable's own before/after pair -- copyfile's internal
    # samefile check calls os.stat too, which would otherwise consume from
    # this same faked sequence for a reason unrelated to what this test is
    # about.
    monkeypatch.setattr(stable.shutil, "copyfile", lambda src, dst: None)

    # Attempt 1: before=(0) after=(1) -- disagree, retried.
    # Attempt 2: before=(2) after=(2) -- agree, settled.
    stats = iter(
        [
            _FakeStat(0, 0),
            _FakeStat(1, 0),
            _FakeStat(2, 0),
            _FakeStat(2, 0),
        ]
    )
    monkeypatch.setattr(stable.os, "stat", lambda path: next(stats))

    tmp, st, settled = stable._read_stable(str(target), retries=3)
    try:
        assert settled is True
    finally:
        os.unlink(tmp)


def test_read_stable_gives_up_after_its_retry_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "f.bin"
    target.write_bytes(b"x")

    monkeypatch.setattr(stable.shutil, "copyfile", lambda src, dst: None)

    sizes = iter(range(20))
    monkeypatch.setattr(stable.os, "stat", lambda path: _FakeStat(next(sizes), 0))

    tmp, st, settled = stable._read_stable(str(target), retries=2)
    try:
        assert settled is False
    finally:
        os.unlink(tmp)


def test_read_stable_sets_the_temp_file_mtime_and_mode_from_the_verified_stat(
    tmp_path: Path,
) -> None:
    target = tmp_path / "f.bin"
    target.write_bytes(b"abc")
    os.chmod(target, 0o600)
    st = target.stat()

    tmp, _, settled = stable._read_stable(str(target), retries=0)
    try:
        assert settled is True
        tmp_st = os.stat(tmp)
        assert tmp_st.st_mtime_ns == st.st_mtime_ns
        assert stat.S_IMODE(tmp_st.st_mode) == stat.S_IMODE(st.st_mode)
    finally:
        os.unlink(tmp)


def test_warn_if_changed_logs_when_the_stat_differs_after_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    target = tmp_path / "f.bin"
    target.write_bytes(b"x")
    before = target.stat()

    # Simulate the file having changed by the time the "after" stat runs.
    monkeypatch.setattr(stable.os, "stat", lambda path: _FakeStat(999, 0))

    with caplog.at_level("WARNING"):
        stable._warn_if_changed(str(target), before)

    assert "changed while being archived" in caplog.text


def test_warn_if_changed_is_silent_when_nothing_changed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    target = tmp_path / "f.bin"
    target.write_bytes(b"x")
    before = target.stat()

    with caplog.at_level("WARNING"):
        stable._warn_if_changed(str(target), before)

    assert caplog.text == ""


def test_warn_if_changed_does_nothing_without_a_before_stat(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    target = tmp_path / "f.bin"
    target.write_bytes(b"x")

    with caplog.at_level("WARNING"):
        stable._warn_if_changed(str(target), None)

    assert caplog.text == ""


def test_warn_if_changed_is_silent_if_the_file_is_gone_by_the_second_stat(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    target = tmp_path / "f.bin"
    target.write_bytes(b"x")
    before = target.stat()
    target.unlink()

    with caplog.at_level("WARNING"):
        stable._warn_if_changed(str(target), before)

    assert caplog.text == ""


def test_a_failed_cleanup_never_replaces_the_extraction_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_extraction(self: _Extractor, workers: object = None) -> None:
        msg = "the extraction's own"
        raise ValueError(msg)

    def fail_cleanup(*args: object, **kwargs: object) -> None:
        msg = "the cleanup's"
        raise RuntimeError(msg)

    src = tmp_path / "a.zip"
    src.write_bytes(b"")
    monkeypatch.setattr(_Extractor, "_zip", fail_extraction)
    monkeypatch.setattr(extractor_module, "remove_path", fail_cleanup)
    extractor = _Extractor(src, tmp_path / "out", _Filter.from_rules((), ()))

    with pytest.raises(ValueError, match="the extraction's own"):
        extractor.run(ArchiveFormat.ZIP, atomic=True)


# --- common: exact-path rule ------------------------------------------------


def test_exact_paths_rule_matches_only_its_paths_and_never_globs() -> None:
    rule = common._exact_paths_rule(["arc[1].zip", "sub/b.zip"])

    assert rule("arc[1].zip", None)
    assert rule("sub/b.zip", None)
    assert not rule("arc1.zip", None)
    assert not rule("deeper/arc[1].zip", None)
    assert not rule("b.zip", None)


# --- compressor: walk and delete_source helpers --------------------------------


def test_compressor_builds_archive_names_from_the_walk_prefix(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "f.txt").write_text("x")

    walked = list(compressor._Compressor(str(tmp_path), _Filter.from_rules((), ())))

    assert [rel for _, rel, _ in walked] == ["a", "a/b", "a/b/f.txt"]


def test_compressor_asks_for_a_junction_only_where_stat_reports_attributes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "f.txt").write_text("x")
    asked: list[str] = []

    def is_link(path: str) -> bool:
        asked.append(Path(path).name)
        return False

    monkeypatch.setattr(compressor, "_is_link", is_link)
    monkeypatch.setattr(compressor, "_HAS_FILE_ATTRIBUTES", False)
    list(compressor._Compressor(str(tmp_path), _Filter.from_rules((), ())))
    assert asked == []

    monkeypatch.setattr(compressor, "_HAS_FILE_ATTRIBUTES", True)
    list(compressor._Compressor(str(tmp_path), _Filter.from_rules((), ())))
    assert asked == ["f.txt"]


def test_ancestors_yields_each_directory_once_outermost_first(tmp_path: Path) -> None:
    walk = compressor._Compressor(str(tmp_path), _Filter.from_rules((), ()))
    emitted: set[str] = set()

    first = [rel for _, rel, _ in walk._ancestors("a/b/c.txt", emitted)]
    second = [rel for _, rel, _ in walk._ancestors("a/b/d/e.txt", emitted)]

    assert first == ["a", "a/b"]
    assert second == ["a/b/d"]
    assert list(walk._ancestors("top.txt", emitted)) == []


def test_remove_all_but_keeps_only_the_path_and_its_directories(tmp_path: Path) -> None:
    (tmp_path / "out" / "deep").mkdir(parents=True)
    (tmp_path / "out" / "deep" / "arc.zip").write_text("a")
    (tmp_path / "out" / "deep" / "other.txt").write_text("x")
    (tmp_path / "out" / "sibling.txt").write_text("x")
    (tmp_path / "gone").mkdir()
    (tmp_path / "gone" / "f.txt").write_text("x")
    (tmp_path / "top.txt").write_text("x")

    compressor._remove_all_but(tmp_path, tmp_path / "out" / "deep" / "arc.zip")

    assert sorted(
        str(p.relative_to(tmp_path)).replace(os.sep, "/") for p in tmp_path.rglob("*")
    ) == [
        "out",
        "out/deep",
        "out/deep/arc.zip",
    ]


# --- rules ----------------------------------------------------------------------


def test_rules_and_filter_are_truthy_only_with_a_rule() -> None:
    assert not _Rules()
    assert _Rules(names=frozenset({"a"}))
    assert _Rules(funcs=(lambda rel, raw: True,))
    assert not _Filter.from_rules((), ())
    assert _Filter.from_rules("a", ())
    assert _Filter.from_rules((), "a")


def test_sort_puts_each_rule_on_its_rung() -> None:
    def pred(rel: str, raw: Any) -> bool:
        return False

    sorted_rules = _Filter.sort(("name", "a/b", "./c", "d/", "/e", "*.log", pred))

    assert sorted_rules.names == frozenset({"name"})
    assert sorted_rules.paths == frozenset({"a/b", "c", "d", "e"})
    assert sorted_rules.funcs == (pred,)
    assert sorted_rules.globs == (() if sorted_rules.spec is not None else ("*.log",))


def test_sort_accepts_any_path_like() -> None:
    class _Fs:
        """An `os.PathLike` that is no `PurePath`."""

        def __fspath__(self) -> str:
            return "x/y"

    assert _Filter.sort((_Fs(),)).paths == frozenset({"x/y"})
    assert _Filter.sort((PurePosixPath("x/y"), PureWindowsPath("x\\z"))).paths == frozenset(
        {"x/y", "x/z"}
    )


def test_sort_is_cached_on_the_rules_but_a_fresh_closure_always_misses() -> None:
    _Filter.sort.cache_clear()

    assert _Filter.sort(("a", "b")) is _Filter.sort(("a", "b"))
    assert _Filter.sort.cache_info().hits == 1

    first = _Filter.sort(((lambda rel, raw: True),))
    second = _Filter.sort(((lambda rel, raw: True),))

    assert first is not second
    assert _Filter.sort.cache_info().hits == 1


def test_from_rules_flattens_nested_rules() -> None:
    flt = _Filter.from_rules(["a", ("b", ["c/d"])], None)

    assert flt.include_rules.names == frozenset({"a", "b"})
    assert flt.include_rules.paths == frozenset({"c/d"})
    assert not flt.exclude_rules


@pytest.mark.parametrize("pathspec", [True, False])
def test_glob_hit_asks_whichever_backend_holds_the_globs(
    monkeypatch: pytest.MonkeyPatch, pathspec: bool
) -> None:
    if pathspec and backends.PathSpec is None:
        pytest.skip("pathspec is not installed")

    if not pathspec:
        monkeypatch.setattr(backends, "PathSpec", None)

    _Filter.sort.cache_clear()

    try:
        side = _Filter.sort(("*.log",))
    finally:
        _Filter.sort.cache_clear()

    assert (side.spec is not None) is pathspec
    assert _Filter.glob_hit("a.log", side)
    assert not _Filter.glob_hit("a.txt", side)
    assert not _Filter.glob_hit("a.log", _Rules())


def test_enter_consults_only_the_exclude_side_rung_by_rung() -> None:
    assert _Filter.from_rules("nothing", ()).enter("any/dir")
    assert not _Filter.from_rules((), "/a/b").enter("a/b")
    assert _Filter.from_rules((), "/a/b").enter("x/a/b")
    assert not _Filter.from_rules((), lambda rel, raw: rel == "p").enter("p")
    assert not _Filter.from_rules((), "logs").enter("deep/logs")
    assert not _Filter.from_rules((), "build*").enter("build-1")
    assert _Filter.from_rules((), "build*").enter("src")


def test_enter_hands_the_entry_to_a_predicate() -> None:
    seen: list[Any] = []
    flt = _Filter.from_rules((), lambda rel, raw: bool(seen.append(raw)))
    marker = object()

    assert flt.enter("d", cast("Any", marker))
    assert seen == [marker]


# --- limiter ---------------------------------------------------------------------


def _limiter(**kw: Any) -> limiter._Limiter:
    """A limiter over `kw`, naming a dummy archive."""
    return limiter._Limiter(ArchiveLimits(**kw), Path("a.zip"))


def _file(name: str, size: int = 1, packed: int = 1, kind: Any = "file") -> limiter._Member:
    """A member of `kind`."""
    return limiter._Member(name, zipfile.ZipInfo(name), size, packed, kind)


@pytest.mark.parametrize(
    ("kw", "members", "match"),
    [
        ({"max_depth": 1}, ["a/b/c"], "nested 2 deep"),
        ({"max_dir_entries": 1}, ["d/a", "d/b"], "directory 'd' holds more"),
        ({"max_root_entries": 1}, ["a", "b"], "root entries"),
        ({"max_file_size": 1}, [("big", 2, 2)], "is 2 bytes"),
        ({"max_ratio": 10}, [("bomb", 1000, 1)], "expands 1000x"),
        ({"max_files": 1}, ["a", "b"], "more than the 1 members"),
        ({"max_total_size": 3}, [("a", 2, 2), ("b", 2, 2)], "past the 3 bytes"),
    ],
)
def test_count_stops_at_each_ceiling(kw: dict[str, int], members: list[Any], match: str) -> None:
    lim = _limiter(**kw)

    with pytest.raises(ArchiveLimitError, match=match):
        for m in members:
            lim.count(_file(m) if isinstance(m, str) else _file(*m))


def test_count_leaves_directories_out_of_max_files_and_tar_out_of_max_ratio() -> None:
    lim = _limiter(max_files=1, max_ratio=1)

    lim.count(_file("d", kind="dir"))
    lim.count(_file("d/tar-member", size=100, packed=0))

    assert (lim.files, lim.total) == (1, 100)


def test_allows_name_admits_the_first_of_each_spelling_and_forget_frees_it() -> None:
    lim = _limiter()

    assert lim.allows_name("a.txt")
    assert not lim.allows_name("./a.txt")
    assert lim.allows_name("A.txt")  # Case is `overwrite`'s business, not a duplicate.

    lim.forget("./a.txt")
    assert lim.allows_name("a.txt")


def test_name_key_drops_dot_segments_and_follows_windows_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(limiter, "_NT", False)
    assert limiter._Limiter._name_key("./d/./a.txt") == "d/a.txt"
    assert limiter._Limiter._name_key("a.txt.") == "a.txt."

    monkeypatch.setattr(limiter, "_NT", True)
    assert limiter._Limiter._name_key("./d/./a.txt. ") == "d/a.txt"


def test_allows_name_raises_under_error() -> None:
    lim = _limiter(duplicates="error")
    lim.allows_name("a")

    with pytest.raises(ArchivePolicyError, match="duplicate member 'a'"):
        lim.allows_name("a")


def test_checked_limits_coerces_policy_strings_and_keeps_the_rest() -> None:
    checked = limiter._checked_limits(
        ArchiveLimits(max_files=3, max_ratio=1.5, symlinks="allow", overwrite="skip")
    )

    assert checked.symlinks is ArchiveLinkPolicy.ALLOW
    assert checked.hardlinks is ArchiveLinkPolicy.ERROR
    assert checked.overwrite is ArchiveOverwritePolicy.SKIP
    assert checked.duplicates is ArchiveDuplicatePolicy.SKIP
    assert (checked.max_files, checked.max_ratio) == (3, 1.5)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {"max_files": 1},
        ArchiveLimits(max_files=-1),
        ArchiveLimits(max_root_entries=False),
        ArchiveLimits(max_dir_entries=2.0),
        ArchiveLimits(dir_check=1),
        ArchiveLimits(hardlinks="nope"),
    ],
)
def test_checked_limits_refuses_malformed_limits(bad: Any) -> None:
    with pytest.raises(ValidationError, match="extract_archive: limits"):
        limiter._checked_limits(bad)


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_allows_link_follows_its_own_kinds_policy(kind: str) -> None:
    field = "symlinks" if kind == "symlink" else "hardlinks"
    link = _file("l", kind=kind)

    assert _limiter(**{field: "allow"}).allows_link(link)
    assert not _limiter(**{field: "skip"}).allows_link(link)

    with pytest.raises(ArchivePolicyError, match=f"{kind} member 'l'"):
        _limiter(**{field: "error"}).allows_link(link)


def test_deny_logs_anything_but_error(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO"):
        assert _limiter()._deny("skip", "thing 'x'") is False

    assert "skipped thing 'x' in a.zip" in caplog.text

    with pytest.raises(ArchivePolicyError, match="a.zip: thing"):
        _limiter()._deny("error", "thing")


def test_fail_always_raises_a_limit_error() -> None:
    with pytest.raises(ArchiveLimitError, match="extract_archive: a.zip: too much"):
        _limiter()._fail("too much")


# --- placement --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("part", "unsafe"),
    [
        ("a.txt:s", True),
        ("C:", True),
        ("CON", True),
        ("con.txt", True),
        ("Com1.tar.gz", True),
        ("LPT\u00b9", True),
        ("NUL  .x", True),
        ("CONIN$", True),
        ("console", False),
        ("COM0", False),
        ("COM10", False),
        ("a.con", False),
        (".", False),
    ],
)
def test_nt_unsafe_segment(part: str, unsafe: bool) -> None:
    assert placement._is_nt_unsafe_segment(part) is unsafe


def test_member_kept_prunes_at_each_directory_and_memoises_it(tmp_path: Path) -> None:
    asked: list[str] = []

    def exclude(rel: str, raw: Any) -> bool:
        asked.append(rel)
        return rel == "a/skip"

    extractor = _ready_extractor(tmp_path)
    extractor.flt = _Filter.from_rules((), exclude)

    assert extractor._member_kept(_file("a/b/f.txt"))
    assert extractor._member_kept(_file("a/b/g.txt"))
    assert not extractor._member_kept(_file("a/skip/h.txt"))
    assert not extractor._member_kept(_file("a/skip/i.txt"))
    assert asked.count("a") == 1
    assert asked.count("a/b") == 1
    assert asked.count("a/skip") == 1


def test_place_logs_a_device_member(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    extractor = _ready_extractor(tmp_path)

    with caplog.at_level("WARNING"):
        assert extractor._place(_file("dev", kind="other")) is None

    assert "never created" in caplog.text


def test_place_frees_the_name_of_a_link_the_policy_skips(tmp_path: Path) -> None:
    extractor = _ready_extractor(tmp_path, ArchiveLimits(symlinks="skip", max_files=0))

    assert extractor._place(_file("l", kind="symlink")) is None
    assert extractor._limiter.files == 0
    assert extractor._limiter.allows_name("l")


# --- members ----------------------------------------------------------------------


@pytest.mark.parametrize("target", ["", "/abs", "C:/x", "\\\\host\\share"])
def test_link_refuses_an_empty_or_absolute_target_with_a_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, target: str
) -> None:
    extractor = _ready_extractor(tmp_path, ArchiveLimits.permissive())
    path = extractor._root / "l"

    extractor._link(_member("l", "hardlink", target=target), path)

    assert not os.path.lexists(path)
    assert "is empty or absolute" in caplog.text


def test_link_judges_a_hardlink_by_the_real_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # The text `sub/real.txt` is inside; the real path (as `resolve` reports it,
    # through a link standing at `sub`) is not, so it is refused.
    extractor = _ready_extractor(tmp_path, ArchiveLimits.permissive())
    (extractor._root / "sub").mkdir()
    (extractor._root / "sub" / "real.txt").write_text("x")
    outside = tmp_path / "outside.txt"
    real_resolve = Path.resolve

    def resolve(self: Path, strict: bool = False) -> Path:
        if self.name == "real.txt":
            return outside
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve)
    target = extractor._root / "h.txt"

    extractor._link(_member("h.txt", "hardlink", target="sub/real.txt"), target)

    assert not target.exists()
    assert "pointing outside" in caplog.text


@pytest.mark.parametrize(
    ("name", "raw", "kept"),
    [
        ("l2", "m/..", False),
        ("l2", "x/m/../f", False),
        ("l2", "./m/./..", False),
        ("sub/l2", "..\\m\\..", False),
        ("sub/l2", "../x", True),
        ("sub/l2", "./.././sub/x", True),
        ("l2", "a/./b", True),
    ],
)
def test_link_refuses_a_symlink_that_climbs_after_descending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    name: str,
    raw: str,
    kept: bool,
) -> None:
    # `m` does not exist yet, so only the text can tell that a later `m -> .`
    # would carry `m/..` out of the destination.
    monkeypatch.setattr(placement, "_NT", False)
    made: list[str] = []
    monkeypatch.setattr(members.os, "symlink", lambda src, dst: made.append(src))
    monkeypatch.setattr(members.os, "replace", lambda src, dst: None)
    extractor = _ready_extractor(tmp_path, ArchiveLimits.permissive())
    (extractor._root / "sub").mkdir()

    extractor._link(_member(name, "symlink", target=raw), extractor._root / name)

    assert made == ([raw] if kept else [])
    assert ("pointing outside" in caplog.text) is not kept


def test_link_refuses_a_target_whose_real_path_cannot_be_worked_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    extractor = _ready_extractor(tmp_path, ArchiveLimits.permissive())

    def loop(self: Path, strict: bool = False) -> NoReturn:
        msg = "Symlink loop"
        raise RuntimeError(msg)

    monkeypatch.setattr(Path, "resolve", loop)
    target = extractor._root / "h.txt"

    extractor._link(_member("h.txt", "hardlink", target="x"), target)

    assert not target.exists()
    assert "pointing outside" in caplog.text


def test_spill_creates_a_new_file_exclusively_and_records_it(tmp_path: Path) -> None:
    extractor = _ready_extractor(tmp_path)
    extractor._built = []
    target = extractor._root / "new.txt"

    extractor._spill(_member("new.txt", "file", size=3), io.BytesIO(b"abc"), target)

    assert target.read_bytes() == b"abc"
    assert extractor._built == [target]


def test_spill_replaces_an_existing_file_through_a_temp_file(tmp_path: Path) -> None:
    extractor = _ready_extractor(tmp_path)
    extractor._built = []
    target = extractor._root / "old.txt"
    target.write_text("old contents")

    extractor._spill(_member("old.txt", "file", size=3), io.BytesIO(b"new"), target)

    assert target.read_bytes() == b"new"
    assert extractor._built == [target]
    assert [p.name for p in extractor._root.iterdir()] == ["old.txt"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_spill_gives_a_replaced_file_the_mode_of_a_new_one(tmp_path: Path) -> None:
    # `mkstemp` would have left every overwritten file at 0600.
    extractor = _ready_extractor(tmp_path)
    old, new = extractor._root / "old.txt", extractor._root / "new.txt"
    old.write_text("old")
    old.chmod(0o640)
    umask = os.umask(0o022)

    try:
        extractor._spill(_member("old.txt", "file", size=3), io.BytesIO(b"abc"), old)
        extractor._spill(_member("new.txt", "file", size=3), io.BytesIO(b"abc"), new)
    finally:
        os.umask(umask)

    assert stat.S_IMODE(old.stat().st_mode) == stat.S_IMODE(new.stat().st_mode) == 0o644


def test_spill_removes_its_temp_file_when_the_member_is_too_big(tmp_path: Path) -> None:
    extractor = _ready_extractor(tmp_path, ArchiveLimits(max_file_size=2))
    target = extractor._root / "old.txt"
    target.write_text("old")

    with pytest.raises(ArchiveLimitError):
        extractor._spill(_member("old.txt", "file", size=1), io.BytesIO(b"toolong"), target)

    assert target.read_text() == "old"
    assert [p.name for p in extractor._root.iterdir()] == ["old.txt"]


def test_spill_logs_and_cleans_up_when_the_replace_fails(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    extractor = _ready_extractor(tmp_path)
    target = extractor._root / "taken"
    target.mkdir()

    extractor._spill(_member("taken", "file", size=1), io.BytesIO(b"x"), target)

    assert target.is_dir()
    assert [p.name for p in extractor._root.iterdir()] == ["taken"]
    assert "could not write 'taken'" in caplog.text


# --- extractor: graft and format detection -----------------------------------------


def test_graft_merges_replaces_and_refuses_as_documented(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    staged, dest = tmp_path / "staged", tmp_path / "dest"
    for root in (staged, dest):
        (root / "both").mkdir(parents=True)

    (staged / "both" / "new.txt").write_text("new")
    (staged / "file.txt").write_text("staged")
    (dest / "file.txt").write_text("dest")
    (staged / "isdir").write_text("staged file")
    (dest / "isdir").mkdir()
    (staged / "isfile").mkdir()
    (staged / "isfile" / "x.txt").write_text("x")
    (dest / "isfile").write_text("dest file")

    extractor = _ready_extractor(tmp_path)

    with caplog.at_level("WARNING"):
        extractor._graft(staged, dest)

    assert (dest / "both" / "new.txt").read_text() == "new"
    assert (dest / "file.txt").read_text() == "staged"
    assert (dest / "isdir").is_dir()
    assert (dest / "isfile").read_text() == "dest file"
    assert "a directory stands at" in caplog.text
    assert "a file stands at" in caplog.text


def test_detect_format_reads_an_empty_zip_and_trusts_bytes_over_a_name(tmp_path: Path) -> None:
    empty = tmp_path / "empty.tar.gz"

    with zipfile.ZipFile(empty, "w"):
        pass

    assert empty.read_bytes()[:4] == b"PK\x05\x06"
    assert _Extractor.detect_format(str(empty)) is ArchiveFormat.ZIP

    zst = tmp_path / "really.zip"
    zst.write_bytes(b"\x28\xb5\x2f\xfd" + bytes(8))

    assert _Extractor.detect_format(str(zst)) is ArchiveFormat.TAR_ZST


# --- stable: copies of read-only files -----------------------------------------------


def test_discard_copies_removes_read_only_copies(tmp_path: Path) -> None:
    copy = tmp_path / "copy"
    copy.write_text("x")
    copy.chmod(stat.S_IREAD)

    stable._discard_copies([str(copy), str(tmp_path / "already-gone")])

    assert not copy.exists()


@pytest.mark.parametrize("fmt", ["zip", "tar"])
def test_a_read_only_guarded_file_leaves_no_stability_copy_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fmt: str
) -> None:
    # The copy took the source's read-only mode, which Windows will not delete.
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    src = tmp_path / "ro.txt"
    src.write_text("x")
    src.chmod(stat.S_IREAD)
    entries = [(str(src), "ro.txt", False)]

    try:
        if fmt == "zip":
            writers._write_zip(entries, io.BytesIO(), 6, None, None, 1, lambda st, p: True)
        else:
            writers._write_tar(
                entries, io.BytesIO(), ArchiveFormat.TAR_GZ, None, None, None, 1, lambda st, p: True
            )
    finally:
        src.chmod(stat.S_IREAD | stat.S_IWRITE)

    assert list(temp.iterdir()) == []
