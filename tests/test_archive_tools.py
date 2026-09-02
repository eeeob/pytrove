"""Covers backup_folder/extract_archive: the filtering rules, the
self-exclusion that keeps an archive out of itself, and the traversal guard
extraction needs because tarfile had none before 3.12."""
import contextlib
import gzip
import io
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import time
import tracemalloc
import zipfile

from concurrent.futures import ThreadPoolExecutor

import pytest

import pytrove
import pytrove._archive_tools as internals
import pytrove.enums
from pytrove import backup_folder, compress_folder, extract_archive
from pytrove.enums import ArchiveFormat
from pytrove.errors import (ArchiveLimitError, ArchivePolicyError,
                            ValidationError)
from pytrove._archive_tools import ArchiveLimits
from pytrove._archive_tools import _Extractor, _Filter

# The optional backends are the modules themselves, or None. There is no
# parallel set of flags any more, so a test forcing one path puts None
# where the module was.
# _resolve_under was folded into _Extractor._place, so the tests that used
# it directly go through _safe_target below instead.



def _safe_target(dest, name, cache=None):
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
    e._limiter = internals._Limiter(ArchiveLimits(), dest)

    if cache is not None:
        e._cleared = cache

    return e._place(internals._Member(name, None, 0, 0, "dir"))
HAS_ZSTD = internals.std_zstd is not None or internals.zstandard is not None


# tar.zst needs the `archive` extra; the other two are stdlib-only.
FORMATS = [ArchiveFormat.ZIP, ArchiveFormat.TAR_GZ] + (
    [ArchiveFormat.TAR_ZST] if HAS_ZSTD else []
)


@pytest.fixture
def tree(tmp_path):
    """A source folder with hidden files, empty dirs and nested content."""

    src = tmp_path / "src"
    (src / "sub" / "deep").mkdir(parents=True)
    (src / "empty").mkdir()
    (src / ".hidden").mkdir()

    (src / "a.py").write_text("a")
    (src / "b.txt").write_text("b")
    (src / "sub" / "c.py").write_text("c")
    (src / "sub" / "deep" / "d.txt").write_text("d")
    (src / ".env").write_text("secret")
    (src / ".hidden" / "x.txt").write_text("x")

    return src


def _names(archive):
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            return {n for n in zf.namelist() if not n.endswith("/")}

    with tarfile.open(archive) as tf:
        return {m.name for m in tf.getmembers() if m.isfile()}


@pytest.mark.parametrize("fmt", FORMATS)
@pytest.mark.parametrize("fsync", [False, True])
def test_round_trip_every_format_and_fsync(tree, tmp_path, fmt, fsync):
    # fsync=True is the default and must be exercised: zstandard's
    # stream_writer closes the file it is handed unless told not to, which
    # made only this combination fail with "flush of closed file".
    archive = backup_folder(tree, tmp_path / "out", format=fmt, fsync=fsync)
    assert archive.exists()

    dest = tmp_path / f"x_{fmt.name}_{fsync}"
    extract_archive(archive, dest)

    got = {
        str(p.relative_to(dest)).replace(os.sep, "/"): p.read_bytes()
        for p in dest.rglob("*") if p.is_file()
    }
    assert got == {
        "a.py": b"a", "b.txt": b"b",
        "sub/c.py": b"c", "sub/deep/d.txt": b"d",
    }


def test_hidden_excluded_by_default(tree, tmp_path):
    assert _names(backup_folder(tree, tmp_path / "h.zip", fsync=False)) == {
        "a.py", "b.txt", "sub/c.py", "sub/deep/d.txt",
    }


def test_hidden_included_when_asked(tree, tmp_path):
    names = _names(backup_folder(tree, tmp_path / "h2.zip", exclude_hidden=False, fsync=False))
    assert ".env" in names and ".hidden/x.txt" in names


def test_naming_a_hidden_file_outright_beats_exclude_hidden(tree, tmp_path):
    # exclude_hidden is an exclude predicate now, not a condition ahead of
    # the filter, so the two include rungs above it win. Naming one file is
    # the whole point of rung 1 -- and it does not let the rest back in.
    assert _names(backup_folder(tree, tmp_path / "h3.zip", include="/.env", fsync=False)) == {
        ".env",
    }


def test_a_hidden_directory_is_still_pruned_past_an_include_glob(tree, tmp_path):
    # A glob is rung 8 and the predicate is rung 4, so the directory loses
    # and is never opened. Same rule as any other exclusion reaching down.
    assert _names(backup_folder(tree, tmp_path / "h4.zip", include=".hidden/**", fsync=False)) == set()


def test_empty_directories_are_not_recorded(tree, tmp_path):
    archive = backup_folder(tree, tmp_path / "e.zip", fsync=False)

    with zipfile.ZipFile(archive) as zf:
        dirs = {n for n in zf.namelist() if n.endswith("/")}

    assert "empty/" not in dirs
    # ...but a directory holding a kept file is still recorded, so an
    # extractor makes the parent before the child.
    assert "sub/" in dirs


def test_include_narrows_to_a_subtree(tree, tmp_path):
    # "**" for the subtree. Nothing carries a directory's verdict down to
    # its contents on the include side, so the pattern has to say what it
    # means -- and this is the one spelling both glob backends agree on.
    assert _names(backup_folder(tree, tmp_path / "i.zip", include="sub/**", fsync=False)) == {
        "sub/c.py", "sub/deep/d.txt",
    }


@pytest.mark.skipif(internals.PathSpec is None, reason="fnmatch has no segment boundary")
def test_a_single_star_stops_at_the_separator(tree, tmp_path):
    # gitignore's rule, and the reason "**" exists at all: "sub/*" is the
    # direct children of sub. Under the fnmatch fallback "*" spans "/" and
    # this matches at every depth instead -- one of the three differences
    # compress_folder documents.
    assert _names(backup_folder(tree, tmp_path / "s.zip", include="sub/*", fsync=False)) == {
        "sub/c.py",
    }


def test_exclude_beats_include(tree, tmp_path):
    names = _names(backup_folder(
        tree, tmp_path / "x.zip", include="*", exclude="*.txt", fsync=False,
    ))
    assert names == {"a.py", "sub/c.py"}


@pytest.mark.parametrize("fmt", FORMATS)
def test_archive_does_not_swallow_itself(tree, tmp_path, fmt):
    # Written into the folder being archived, and to the same name twice:
    # without skipping the destination (and the temp file it is written
    # through) the second run would contain the first.
    sizes = [
        backup_folder(
            tree, tree / f"self.{fmt.value}", format=fmt, exclude_hidden=False, fsync=False,
        ).stat().st_size
        for _ in range(3)
    ]
    assert len(set(sizes)) == 1


def test_dest_directory_names_archive_after_source(tree, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    assert backup_folder(tree, out, fsync=False).name == "src.zip"


def test_rejects_a_file_as_source(tree, tmp_path):
    from pytrove.errors import ValidationError

    with pytest.raises(ValidationError):
        backup_folder(tree / "a.py", tmp_path / "no.zip")


@pytest.mark.parametrize("name", [
    "../escape.txt",
    "../../escape.txt",
    "a/../../escape.txt",
    "..\\escape.txt",
    "",
])
def test_safe_target_refuses_traversal(tmp_path, name):
    dest = tmp_path / "dest"
    dest.mkdir()
    assert _safe_target(dest, name) is None


@pytest.mark.parametrize("name", [
    "../escape.txt", "../../escape.txt", "a/../../escape.txt", "..\\escape.txt",
    "", "/", "///", "C:/Windows/x", "c:x", "sub/../../escape.txt",
    "pkg/a.py", "a/../b.txt", "sub/./a.txt", "/etc/passwd", "plain.txt",
])
def test_the_directory_cache_never_changes_the_verdict(tmp_path, name):
    # _safe_target resolves the directory part once and reuses it for
    # siblings. That is only sound if it decides exactly what the
    # per-member resolve decided.
    dest = tmp_path / "dest"
    dest.mkdir()

    assert _safe_target(dest, name, {}) == _safe_target(dest, name)


def test_a_junction_inside_dest_cannot_be_written_through(tmp_path):
    # The one thing resolve() buys over folding ".." by hand, and the
    # reason the cache keys on the directory: a link that already sits in
    # dest points elsewhere, so a member named "sub/x" lands outside while
    # its own name looks harmless.
    dest = tmp_path / "dest"
    dest.mkdir()
    outside = tmp_path / "OUTSIDE"
    outside.mkdir()

    link = dest / "sub"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            pytest.skip("cannot create a link here")
        # Windows refuses symlinks without privilege; a junction needs none.
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True, check=False,
        )
        if made.returncode != 0:
            pytest.skip("cannot create a junction here")

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("sub/PWNED.txt", "PWNED")
        zf.writestr("ok.txt", "fine")

    extract_archive(evil, dest)

    assert list(outside.iterdir()) == []
    assert (dest / "ok.txt").read_text() == "fine"


@pytest.mark.parametrize("name", [
    "/etc/passwd", "C:/Windows/x", "c:x", "//server/share/x", "/",
])
def test_absolute_names_are_refused_outright(tmp_path, name):
    # tar strips the leading separator and keeps such a member. This does
    # not: rewriting where the archive asked to go is a silent repair, and
    # an archive that asks to write outside the directory it was handed has
    # not earned the benefit of the doubt on its other names either.
    dest = tmp_path / "dest"
    dest.mkdir()

    assert _safe_target(dest, name) is None


def test_extract_refuses_to_escape_the_destination(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    victim = tmp_path / "VICTIM.txt"
    victim.write_text("ORIGINAL")

    evil = tmp_path / "evil.zip"

    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../VICTIM.txt", "PWNED")
        zf.writestr("ok.txt", "fine")

    extract_archive(evil, dest)

    assert victim.read_text() == "ORIGINAL"
    assert (dest / "ok.txt").read_text() == "fine"


def test_extract_skips_symlink_members(tmp_path):
    # A symlink member can point anywhere; a later member written "through"
    # it would land outside despite its own name looking harmless.
    dest = tmp_path / "dest"
    dest.mkdir()
    evil = tmp_path / "evil.tar.gz"

    with tarfile.open(evil, "w:gz") as tf:
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = str(tmp_path)
        tf.addfile(link)

        data = b"fine"
        info = tarfile.TarInfo("ok.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))

    # symlinks defaults to ERROR, so skipping is what this asks for --
    # the point being that the member is left out rather than followed.
    extract_archive(evil, dest, limits=ArchiveLimits(symlinks="skip"))

    assert not (dest / "link").is_symlink()
    assert (dest / "ok.txt").read_bytes() == b"fine"


@pytest.mark.parametrize("fmt", FORMATS)
def test_format_detected_from_content_not_extension(tree, tmp_path, fmt):
    archive = backup_folder(tree, tmp_path / "out", format=fmt, fsync=False)
    renamed = archive.with_name("mystery.bin")
    archive.rename(renamed)

    dest = tmp_path / f"d_{fmt.name}"
    extract_archive(renamed, dest)

    assert (dest / "a.py").read_bytes() == b"a"


@pytest.fixture
def repeated(tmp_path):
    """A tree where the same directory name occurs at three depths."""

    src = tmp_path / "rep"
    (src / "logs").mkdir(parents=True)
    (src / "app" / "logs").mkdir(parents=True)
    (src / "srv" / "deep" / "logs").mkdir(parents=True)
    (src / "logs" / "root.log").write_text("r")
    (src / "app" / "logs" / "app.log").write_text("a")
    (src / "srv" / "deep" / "logs" / "deep.log").write_text("d")
    (src / "app" / "main.py").write_text("m")

    return src


def test_a_bare_name_matches_at_every_depth(repeated, tmp_path):
    assert _names(backup_folder(repeated, tmp_path / "b.zip", exclude="logs", fsync=False)) == {
        "app/main.py",
    }


def test_a_leading_slash_anchors_to_the_root(repeated, tmp_path):
    # The only way to say "the top-level one, not every one". Before this
    # was supported such a pattern matched nothing at all, silently.
    assert _names(backup_folder(repeated, tmp_path / "a.zip", exclude="/logs", fsync=False)) == {
        "app/logs/app.log", "app/main.py", "srv/deep/logs/deep.log",
    }


def test_the_anchor_works_for_include_too(tree, tmp_path):
    (tree / "sub" / "a.py").write_text("nested")

    assert _names(backup_folder(tree, tmp_path / "i.zip", include="/a.py", fsync=False)) == {"a.py"}
    assert _names(backup_folder(tree, tmp_path / "j.zip", include="a.py", fsync=False)) == {
        "a.py", "sub/a.py",
    }


def test_names_may_repeat_within_one_path(tmp_path):
    # "logs/logs/logs/logs" is a file called logs inside three directories
    # called logs. The ancestor bookkeeping keys on the full branch, not the
    # basename, which is what keeps the levels distinct.
    src = tmp_path / "deep"
    (src / "logs" / "logs" / "logs").mkdir(parents=True)
    (src / "logs" / "logs" / "logs" / "logs").write_text("deep")
    (src / "logs" / "logs" / "logs.txt").write_text("mid")

    archive = backup_folder(src, tmp_path / "d.zip", fsync=False)
    extract_archive(archive, tmp_path / "dx")

    assert (tmp_path / "dx" / "logs" / "logs" / "logs" / "logs").read_text() == "deep"
    assert (tmp_path / "dx" / "logs" / "logs" / "logs.txt").read_text() == "mid"


def test_traversal_attempts_are_logged(tmp_path, caplog):
    dest = tmp_path / "dest"
    evil = tmp_path / "evil.zip"

    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("ok.txt", "fine")
        zf.writestr("../VICTIM.txt", "PWNED")

    with caplog.at_level("WARNING", logger="pytrove._archive_tools"):
        extract_archive(evil, dest)

    assert "refused unsafe member name" in caplog.text
    assert "../VICTIM.txt" in caplog.text


def test_non_regular_members_are_logged(tmp_path, caplog):
    evil = tmp_path / "evil.tar.gz"

    with tarfile.open(evil, "w:gz") as tf:
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = str(tmp_path)
        tf.addfile(link)

    with caplog.at_level("INFO", logger="pytrove._archive_tools"):
        extract_archive(evil, tmp_path / "d", limits=ArchiveLimits(symlinks="skip"))

    assert "skipped symlink member" in caplog.text


def test_an_unreadable_file_is_logged_rather_than_dropped_in_silence(tree, tmp_path, caplog, monkeypatch):
    # A backup missing a file it could not read must not look identical to
    # one that never had it.
    import zipfile as zf_mod

    real = zf_mod.ZipFile.write

    def failing(self, filename, arcname=None, *a, **kw):
        if str(filename).endswith("b.txt"):
            raise PermissionError(13, "Permission denied")
        return real(self, filename, arcname, *a, **kw)

    monkeypatch.setattr(zf_mod.ZipFile, "write", failing)

    with caplog.at_level("WARNING", logger="pytrove._archive_tools"):
        archive = compress_folder(tree, tmp_path / "u.zip", fsync=False)

    assert "b.txt" not in _names(archive)
    assert "skipped" in caplog.text


def test_a_clean_run_logs_nothing(tree, tmp_path, caplog):
    with caplog.at_level("WARNING", logger="pytrove._archive_tools"):
        archive = backup_folder(tree, tmp_path / "c.zip", fsync=False)
        extract_archive(archive, tmp_path / "cx")

    assert caplog.text == ""


# zstd has two backends: compression.zstd from 3.14 (PEP 784) and the
# third-party zstandard below that. Only one may be present, so each is
# skipped when it is not.
ZSTD_BACKENDS = [
    pytest.param("stdlib", marks=pytest.mark.skipif(
        internals.std_zstd is None, reason="no compression.zstd (needs 3.14+)")),
    pytest.param("zstandard", marks=pytest.mark.skipif(
        internals.zstandard is None, reason="zstandard not installed")),
]


@pytest.fixture
def backend(request, monkeypatch):
    """Force one zstd backend for the duration of a test."""

    if request.param == "zstandard":
        monkeypatch.setattr(internals, "std_zstd", None)

    return request.param


@pytest.mark.skipif(not HAS_ZSTD, reason="no zstd backend")
@pytest.mark.parametrize("backend", ZSTD_BACKENDS, indirect=True)
@pytest.mark.parametrize("fsync", [False, True])
def test_each_zstd_backend_round_trips(tree, tmp_path, backend, fsync):
    # fsync=True matters here: a backend that closes the handle it was
    # given breaks atomic_write's flush, which is exactly how the
    # third-party one behaved until told closefd=False.
    archive = compress_folder(
        tree, tmp_path / f"z_{backend}.tar.zst", format="tar.zst", fsync=fsync,
    )
    extract_archive(archive, tmp_path / f"zx_{backend}_{fsync}")

    assert (tmp_path / f"zx_{backend}_{fsync}" / "sub" / "c.py").read_bytes() == b"c"


@pytest.mark.skipif(not HAS_ZSTD, reason="no zstd backend")
@pytest.mark.parametrize("backend", ZSTD_BACKENDS, indirect=True)
def test_each_zstd_backend_accepts_workers(tree, tmp_path, backend):
    # The stdlib takes it as options[nb_workers], zstandard as threads=.
    archive = compress_folder(
        tree, tmp_path / f"w_{backend}.tar.zst", format="tar.zst", workers=-1, fsync=False,
    )
    extract_archive(archive, tmp_path / f"wx_{backend}")

    assert (tmp_path / f"wx_{backend}" / "a.py").read_bytes() == b"a"


@pytest.mark.skipif(
    internals.std_zstd is None or internals.zstandard is None,
    reason="needs both backends to compare them",
)
def test_the_two_zstd_backends_read_each_other(tree, tmp_path, monkeypatch):
    made = {}
    real = internals.std_zstd

    for name in ("stdlib", "zstandard"):
        monkeypatch.setattr(internals, "std_zstd", real if name == "stdlib" else None)
        made[name] = compress_folder(
            tree, tmp_path / f"{name}.tar.zst", format="tar.zst", fsync=False,
        )

    for written, archive in made.items():
        for reader in ("stdlib", "zstandard"):
            monkeypatch.setattr(internals, "std_zstd",
                                real if reader == "stdlib" else None)
            out = tmp_path / f"o_{written}_{reader}"
            extract_archive(archive, out)

            assert (out / "sub" / "deep" / "d.txt").read_bytes() == b"d"


def test_missing_both_backends_names_the_right_cure(tree, tmp_path, monkeypatch):
    # _require_zstd reads the two backend handles from where they are
    # imported, which is _archive_tools -- archive_tools calls it, it does
    # not hold them.
    import pytrove._archive_tools as internals

    monkeypatch.setattr(internals, "std_zstd", None)
    monkeypatch.setattr(internals, "zstandard", None)

    with pytest.raises(ImportError) as caught:
        compress_folder(tree, tmp_path / "n.tar.zst", format="tar.zst")

    message = str(caught.value)

    # On 3.14 the extra installs nothing, so pointing there would send
    # someone to install a package they do not need and leave them stuck.
    if sys.version_info >= (3, 14):
        assert "built without" in message
        assert "pytrove[archive]" not in message
    else:
        assert "pytrove[archive]" in message


def test_backup_folder_is_the_old_name_for_compress_folder():
    assert backup_folder is compress_folder
    assert {"backup_folder", "compress_folder", "extract_archive"} <= set(pytrove.__all__)


# Compression takes workers (fastzip when it is there, this thread when
# not); extraction takes none at all any more. Every writing mode still has
# to produce an archive every reading path can open.
WRITE_MODES = [{}, {"workers": 1}, {"workers": 4}, {"workers": -1},
               {"workers": ThreadPoolExecutor}]


@pytest.mark.parametrize("fmt", FORMATS)
@pytest.mark.parametrize("write_kw", WRITE_MODES)
def test_every_write_mode_round_trips(tree, tmp_path, fmt, write_kw):
    with ThreadPoolExecutor(4) as pool:
        kw = {k: (pool if v is ThreadPoolExecutor else v) for k, v in write_kw.items()}
        archive = compress_folder(tree, tmp_path / "a", format=fmt, fsync=False, **kw)

    out = tmp_path / "out"
    extract_archive(archive, out)

    got = {
        str(p.relative_to(out)).replace(os.sep, "/"): p.read_bytes()
        for p in out.rglob("*") if p.is_file()
    }
    assert got == {
        "a.py": b"a", "b.txt": b"b",
        "sub/c.py": b"c", "sub/deep/d.txt": b"d",
    }


@pytest.mark.parametrize("bad", ["4", 2.5, True, object()])
def test_workers_refuses_what_it_cannot_read(tree, tmp_path, bad):
    # One argument for a count or a pool, and anything else is a mistake
    # worth hearing about. True is in the list on purpose: bool is an int
    # in Python, so it would otherwise pass silently as workers=1.
    from pytrove.errors import ValidationError

    with pytest.raises(ValidationError, match="count or an executor"):
        compress_folder(tree, tmp_path / "bad.zip", workers=bad, fsync=False)


def test_a_rejected_workers_value_leaves_no_archive_behind(tree, tmp_path):
    from pytrove.errors import ValidationError

    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(ValidationError):
        compress_folder(tree, out / "bad.zip", workers="4", fsync=False)

    assert list(out.iterdir()) == []


def test_extract_archive_takes_workers_but_not_executor(tree, tmp_path):
    # One argument, exactly as compress_folder takes it. `executor` was
    # never a separate knob here and is not becoming one.
    archive = compress_folder(tree, tmp_path / "w.zip", fsync=False)

    extract_archive(archive, tmp_path / "x_ok", workers=4)

    with pytest.raises(TypeError):
        extract_archive(archive, tmp_path / "x_dead", executor=4)


def _threads_that_compressed(fn, monkeypatch):
    """Which threads actually ran the per-file work while `fn` executed.

    Sampling threading.active_count() from a watcher was the obvious way to
    ask this and a bad one: a pool over a handful of files is created and
    joined between two 1 ms samples, so the test failed about two runs in
    five for no reason at all. Recording the thread that ran each unit of
    work answers the real question -- did this happen on the caller's
    thread? -- and cannot race.
    """

    seen = set()
    real = zipfile.ZipFile.write

    def spy(self, *args, **kw):
        seen.add(threading.get_ident())
        return real(self, *args, **kw)

    monkeypatch.setattr(zipfile.ZipFile, "write", spy)
    fn()

    return seen


@pytest.mark.parametrize("kw", [{}, {"workers": 1}])
def test_the_default_compresses_on_the_calling_thread(tree, tmp_path, kw, monkeypatch):
    # The default creates no threads: nothing gets a pool underneath it
    # unless it asked, and workers=1 has to mean the same as not asking.
    used = _threads_that_compressed(
        lambda: compress_folder(tree, tmp_path / "s.zip", fsync=False, **kw), monkeypatch,
    )

    assert used == {threading.get_ident()}


@pytest.mark.skipif(internals.WZip is None, reason="fastzip not importable here")
def test_workers_goes_through_fastzip(tree, tmp_path, monkeypatch):
    # With fastzip present, asking for workers must not fall back to the
    # serial zipfile path -- ZipFile.write should never be reached.
    used = _threads_that_compressed(
        lambda: compress_folder(tree, tmp_path / "p.zip", workers=4, fsync=False), monkeypatch,
    )

    assert used == set()


@pytest.mark.skipif(internals.WZip is not None, reason="needs fastzip to be absent")
def test_workers_without_fastzip_warns_and_still_works(tree, tmp_path, caplog):
    # Degrading in silence is the thing this library refuses to do: the
    # archive is still correct, only slower, and the log says why.
    with caplog.at_level("WARNING", logger="pytrove._archive_tools"):
        archive = compress_folder(tree, tmp_path / "nf.zip", workers=4, fsync=False)

    assert "fastzip" in caplog.text
    assert _names(archive) == {"a.py", "b.txt", "sub/c.py", "sub/deep/d.txt"}


@pytest.mark.skipif(sys.platform != "win32", reason="hidden attribute is Windows-only")
def test_windows_hidden_attribute_is_honoured(tmp_path):
    src = tmp_path / "s"
    src.mkdir()
    (src / "plain.txt").write_text("p")
    marked = src / "marked.txt"
    marked.write_text("m")
    subprocess.run(["attrib", "+H", str(marked)], capture_output=True, check=False)

    assert _names(backup_folder(src, tmp_path / "w.zip", fsync=False)) == {"plain.txt"}


# --- limits ---------------------------------------------------------------

def _bomb(path, ratio_mb=200):
    """An archive whose one member expands enormously. The real thing."""

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bomb.bin", b"\0" * (ratio_mb * 1024 * 1024))

    return path


def test_no_limits_by_default(tree, tmp_path):
    # Adding a ceiling that refused archives which used to extract would
    # break working code, so nothing is capped unless asked.
    archive = compress_folder(tree, tmp_path / "n.zip", fsync=False)
    extract_archive(archive, tmp_path / "nx")

    assert (tmp_path / "nx" / "a.py").read_bytes() == b"a"


def test_a_zip_bomb_is_refused_before_it_is_written(tmp_path):
    from pytrove.errors import ArchiveLimitError

    bomb = _bomb(tmp_path / "bomb.zip")
    dest = tmp_path / "out"

    assert bomb.stat().st_size < 1_000_000  # 200 MB of zeros, stored tiny

    with pytest.raises(ArchiveLimitError, match="expands"):
        extract_archive(bomb, dest, limits=ArchiveLimits(max_ratio=100))

    # Nothing of the bomb reached the disk.
    assert not any(p.is_file() for p in dest.rglob("*"))


@pytest.mark.parametrize("limits,match", [
    (dict(max_files=2), "more than the 2"),
    (dict(max_total_size=3), "expands past"),
    (dict(max_file_size=0), "over the 0"),
    (dict(max_depth=1), "nested"),
])
def test_each_limit_refuses_what_it_names(tree, tmp_path, limits, match):
    from pytrove.errors import ArchiveLimitError

    archive = compress_folder(tree, tmp_path / "l.zip", fsync=False)

    with pytest.raises(ArchiveLimitError, match=match):
        extract_archive(archive, tmp_path / "lx", limits=ArchiveLimits(**limits))


@pytest.mark.parametrize("fmt", FORMATS)
def test_limits_apply_to_every_format(tree, tmp_path, fmt):
    from pytrove.errors import ArchiveLimitError

    archive = compress_folder(tree, tmp_path / "f", format=fmt, fsync=False)

    with pytest.raises(ArchiveLimitError):
        extract_archive(archive, tmp_path / "fx", limits=ArchiveLimits(max_files=1))


def test_a_generous_limit_lets_everything_through(tree, tmp_path):
    archive = compress_folder(tree, tmp_path / "g.zip", fsync=False)
    extract_archive(
        archive, tmp_path / "gx",
        limits=ArchiveLimits(max_files=1000, max_total_size=1 << 30,
                              max_file_size=1 << 20, max_ratio=1000, max_depth=10,
                              max_dir_entries=100),
    )

    assert (tmp_path / "gx" / "sub" / "deep" / "d.txt").read_bytes() == b"d"


def _extracted_into(arc, dest, **kw):
    extract_archive(arc, dest, **kw)

    return sorted(str(p.relative_to(dest)).replace(os.sep, "/")
                  for p in dest.rglob("*") if p.is_file() or p.is_symlink())


def _tar_of(tmp_path, members):
    """A tar.gz built member by member, so link and device types can be in it."""

    path = tmp_path / "made.tar.gz"

    with tarfile.open(path, "w:gz") as tf:
        for name, kind, data, link in members:
            info = tarfile.TarInfo(name)

            if kind == "sym":
                info.type, info.linkname = tarfile.SYMTYPE, link
            elif kind == "hard":
                info.type, info.linkname = tarfile.LNKTYPE, link
            elif kind == "fifo":
                info.type = tarfile.FIFOTYPE
            else:
                info.size = len(data)

            tf.addfile(info, io.BytesIO(data) if kind == "file" else None)

    return path


# --- what a member name may be --------------------------------------------

@pytest.mark.parametrize("name", [
    "/etc/passwd", "C:/Windows/x", "c:x", "//server/share/x", "/", "///",
])
def test_an_absolute_member_name_is_refused_not_repaired(tmp_path, name):
    # tar strips the leading separator and keeps the member. This does not:
    # rewriting where the archive asked to go is a silent repair, and an
    # archive asking to write outside its destination has not earned the
    # benefit of the doubt on its other names either.
    dest = tmp_path / "dest"
    dest.mkdir()

    assert _safe_target(dest, name) is None


# --- the policies ----------------------------------------------------------

def test_symlinks_stop_the_extraction_by_default_and_can_be_skipped(tmp_path):
    # A link is the one member still dangerous after its own name has been
    # checked -- what it points at is a second name, read later, by
    # something that has forgotten where it came from. So an archive
    # carrying one is not extracted quietly.
    arc = _tar_of(tmp_path, [("real.txt", "file", b"r", None),
                             ("in.lnk", "sym", None, "real.txt")])

    with pytest.raises(ArchivePolicyError, match="symlink member"):
        extract_archive(arc, tmp_path / "a")

    assert _extracted_into(arc, tmp_path / "b",
                           limits=ArchiveLimits(symlinks="skip")) == ["real.txt"]


def test_a_link_pointing_outside_is_refused_even_when_allowed(tmp_path):
    # Containment is not the callers to waive: a later member written
    # "through" an escaping link lands outside while its own name looks
    # harmless, which is the whole reason link members are dangerous.
    arc = _tar_of(tmp_path, [("real.txt", "file", b"r", None),
                             ("out.lnk", "sym", None, "../../escape")])

    assert "out.lnk" not in _extracted_into(arc, tmp_path / "c",
                                            limits=ArchiveLimits.permissive())


def test_a_device_member_is_refused_whatever_the_policy(tmp_path):
    arc = _tar_of(tmp_path, [("a.txt", "file", b"a", None),
                             ("pipe", "fifo", None, None)])

    assert _extracted_into(arc, tmp_path / "d", limits=ArchiveLimits.permissive()) == ["a.txt"]


def test_duplicate_members(tmp_path):
    arc = tmp_path / "dup.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("same.txt", "first")
        zf.writestr("same.txt", "second")

    assert _extracted_into(arc, tmp_path / "e") == ["same.txt"]
    assert (tmp_path / "e" / "same.txt").read_text() == "first"

    with pytest.raises(ArchivePolicyError, match="duplicate member"):
        extract_archive(arc, tmp_path / "f", limits=ArchiveLimits(duplicates="error"))


@pytest.mark.parametrize("policy,expected", [
    ("overwrite", "new"), ("skip", "old"), ("error", None),
])
def test_overwrite_policy(tmp_path, policy, expected):
    arc = tmp_path / "p.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("a.txt", "new")

    dest = tmp_path / ("o_" + policy)
    dest.mkdir()
    (dest / "a.txt").write_text("old")

    if expected is None:
        with pytest.raises(ArchivePolicyError, match="already exists"):
            extract_archive(arc, dest, limits=ArchiveLimits(overwrite=policy))
    else:
        extract_archive(arc, dest, limits=ArchiveLimits(overwrite=policy))
        assert (dest / "a.txt").read_text() == expected


# --- when the decisions happen, and where the bytes land -------------------

def test_a_breach_part_way_through_leaves_what_came_before_it(tmp_path):
    # Every member is written as it is read, so a breach on the third one
    # has already put the first two somewhere. Where, and whether they
    # stay, is what the two arguments decide: atomic is on by default and
    # they never reached `dest` at all, turning it off puts them there and
    # leaves them -- what came out before the archive turned out to be
    # wrong is sometimes the useful thing -- and cleanup_on_error then
    # takes them back again.
    arc = _tar_of(tmp_path, [("first.txt", "file", b"x" * 100, None),
                             ("second.txt", "file", b"x" * 100, None),
                             ("huge.bin", "file", b"x" * 500000, None)])
    seq = [0]

    def leftovers(**kw):
        seq[0] += 1
        dest = tmp_path / ("z%d" % seq[0])

        with pytest.raises(ArchiveLimitError):
            extract_archive(arc, dest,
                            limits=ArchiveLimits(max_total_size=1000), **kw)

        return sorted(p.name for p in dest.iterdir()) if dest.exists() else []

    assert leftovers() == []
    assert leftovers(atomic=False) == ["first.txt", "second.txt"]
    assert leftovers(atomic=False, cleanup_on_error=True) == []


def test_cleanup_on_error_removes_only_what_this_run_created(tmp_path):
    arc = _tar_of(tmp_path, [("keep/a.txt", "file", b"x" * 100, None),
                             ("keep/b.txt", "file", b"x" * 100, None),
                             ("huge.bin", "file", b"x" * 500000, None)])

    dest = tmp_path / "mixed"
    (dest / "keep").mkdir(parents=True)
    (dest / "keep" / "mine.txt").write_text("mine")
    (dest / "top.txt").write_text("top")

    with pytest.raises(ArchiveLimitError):
        extract_archive(arc, dest, cleanup_on_error=True,
                        limits=ArchiveLimits(max_total_size=1000))

    # "keep" was already there, so it stays and so does what was in it --
    # only the two files this run put inside it are gone.
    assert (dest / "keep" / "mine.txt").read_text() == "mine"
    assert (dest / "top.txt").read_text() == "top"
    assert not (dest / "keep" / "a.txt").exists()
    assert not (dest / "keep" / "b.txt").exists()


def test_cleanup_on_error_removes_a_directory_it_created_itself(tmp_path):
    arc = _tar_of(tmp_path, [("made/a.txt", "file", b"x" * 100, None),
                             ("huge.bin", "file", b"x" * 500000, None)])

    dest = tmp_path / "fresh"
    dest.mkdir()

    with pytest.raises(ArchiveLimitError):
        extract_archive(arc, dest, cleanup_on_error=True,
                        limits=ArchiveLimits(max_total_size=1000))

    assert list(dest.iterdir()) == []


def test_what_came_out_before_the_breach_is_kept_when_asked_for(tmp_path):
    # atomic=False with cleanup_on_error=False is how a caller says the
    # half-extracted tree is the useful thing. Nothing is taken back then,
    # not even the directory this run made to hold it.
    arc = _tar_of(tmp_path, [("made/a.txt", "file", b"x" * 100, None),
                             ("huge.bin", "file", b"x" * 500000, None)])

    dest = tmp_path / "kept"

    with pytest.raises(ArchiveLimitError):
        extract_archive(arc, dest, atomic=False, cleanup_on_error=False,
                        limits=ArchiveLimits(max_total_size=1000))

    assert (dest / "made" / "a.txt").read_text() == "x" * 100


def test_atomic_leaves_what_was_there_when_it_fails(tmp_path):
    arc = _tar_of(tmp_path, [("new.txt", "file", b"n", None),
                             ("huge.bin", "file", b"x" * 500000, None)])
    dest = tmp_path / "keep"
    dest.mkdir()
    (dest / "kept.txt").write_text("kept")

    with pytest.raises(ArchiveLimitError):
        extract_archive(arc, dest, atomic=True, limits=ArchiveLimits(max_total_size=1000))

    assert sorted(p.name for p in dest.iterdir()) == ["kept.txt"]


def test_atomic_merges_into_an_existing_destination(tmp_path):
    # The staged tree used to be swapped in for the whole destination,
    # which threw away every file the archive did not happen to name --
    # and only on the branch asked for because it is the careful one.
    arc = tmp_path / "r.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("new.txt", "new")
        zf.writestr("lib/b.txt", "B")

    dest = tmp_path / "swap"
    (dest / "lib").mkdir(parents=True)
    (dest / "stale.txt").write_text("stale")
    (dest / "lib" / "mine.txt").write_text("mine")

    extract_archive(arc, dest, atomic=True)

    assert sorted(p.name for p in dest.iterdir()) == ["lib", "new.txt", "stale.txt"]
    assert sorted(p.name for p in (dest / "lib").iterdir()) == ["b.txt", "mine.txt"]
    assert (dest / "stale.txt").read_text() == "stale"
    assert (dest / "lib" / "mine.txt").read_text() == "mine"
    assert not list(tmp_path.glob(".*.tmp"))


def test_atomic_overwrites_only_the_names_the_archive_carries(tmp_path):
    arc = tmp_path / "r.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("same.txt", "from the archive")

    dest = tmp_path / "swap"
    dest.mkdir()
    (dest / "same.txt").write_text("was here first")

    extract_archive(arc, dest, atomic=True)

    assert (dest / "same.txt").read_text() == "from the archive"


def test_atomic_asks_overwrite_about_the_destination_not_the_staging_dir(tmp_path):
    # Nothing can already exist in a directory made seconds ago, so a
    # policy asked about the staging tree would always say yes.
    arc = tmp_path / "r.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("same.txt", "from the archive")

    dest = tmp_path / "swap"
    dest.mkdir()
    (dest / "same.txt").write_text("was here first")

    extract_archive(arc, dest, atomic=True,
                    limits=ArchiveLimits(overwrite="skip"))

    assert (dest / "same.txt").read_text() == "was here first"


def test_members_land_in_dest_itself_not_in_a_folder_named_after_the_archive(tmp_path):
    src = tmp_path / "backup"
    (src / "lib").mkdir(parents=True)
    (src / "a.txt").write_text("A")
    (src / "lib" / "b.txt").write_text("B")

    arc = compress_folder(src, tmp_path / "backup.zip")

    for atomic in (False, True):
        dest = tmp_path / f"out-{atomic}"
        extract_archive(arc, dest, atomic=atomic)

        assert not (dest / "backup").exists()
        assert (dest / "a.txt").read_text() == "A"
        assert (dest / "lib" / "b.txt").read_text() == "B"


def test_an_empty_path_segment_is_refused_rather_than_folded(tmp_path):
    # "a//b.txt" would otherwise register a directory literally named "a/"
    # against max_dir_entries and put that same "a/" to dir_check.
    arc = tmp_path / "r.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("a//b.txt", "B")
        zf.writestr("a/c.txt", "C")

    dest = tmp_path / "out"
    seen = []
    extract_archive(arc, dest, limits=ArchiveLimits(
        dir_check=lambda p: seen.append(p.name)))

    assert not (dest / "a" / "b.txt").exists()
    assert (dest / "a" / "c.txt").read_text() == "C"
    assert seen == ["a"]


def test_a_corrupt_member_stops_the_extraction(tmp_path):
    # A bad checksum is the archive being wrong, so it is never swallowed:
    # zipfile raises on it and nothing here catches it. What the member had
    # already written stays unless cleanup_on_error says otherwise.
    arc = tmp_path / "bad.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("a.txt", "hello")

    blob = bytearray(arc.read_bytes())
    blob[blob.index(b"hello")] = ord("H")      # break the CRC, keep the size
    arc.write_bytes(bytes(blob))

    with pytest.raises(zipfile.BadZipFile, match="CRC"):
        extract_archive(arc, tmp_path / "vf")

    dest = tmp_path / "vf2"

    with pytest.raises(zipfile.BadZipFile, match="CRC"):
        extract_archive(arc, dest, cleanup_on_error=True)

    assert not dest.exists() or list(dest.iterdir()) == []


# --- workers ---------------------------------------------------------------

@pytest.mark.parametrize("workers", [None, 1, 4, -1])
def test_extraction_workers_change_nothing_but_the_threads(tree, tmp_path, workers):
    archive = compress_folder(tree, tmp_path / "w.zip", fsync=False)
    serial = tmp_path / "serial"
    parallel = tmp_path / ("par_%s" % workers)

    extract_archive(archive, serial)
    extract_archive(archive, parallel, workers=workers)

    assert (sorted(str(p.relative_to(serial)) for p in serial.rglob("*"))
            == sorted(str(p.relative_to(parallel)) for p in parallel.rglob("*")))


@pytest.mark.parametrize("label,workers", [
    ("count", 4), ("one", 1), ("zero", 0),
    ("str", "4"), ("bool", True), ("float", 2.5), ("pool", ThreadPoolExecutor),
])
def test_workers_on_a_tar_is_ignored_and_said_so(tree, tmp_path, caplog, label, workers):
    # A tar is one stream read in order, so the argument buys nothing and is
    # not looked at -- not even its type, since refusing a value that is
    # about to be ignored would be a distinction without a difference. What
    # the caller gets instead is a line saying it changed nothing.
    archive = compress_folder(tree, tmp_path / "w.tar.gz", format="tar.gz", fsync=False)
    dest = tmp_path / f"tx_{label}"

    if workers is ThreadPoolExecutor:
        workers = ThreadPoolExecutor(2)

    try:
        with caplog.at_level("WARNING", logger="pytrove._archive_tools"):
            extract_archive(archive, dest, workers=workers)
    finally:
        if isinstance(workers, ThreadPoolExecutor):
            workers.shutdown()

    assert "workers was ignored" in caplog.text
    assert (dest / "sub" / "deep" / "d.txt").read_bytes() == b"d"


def test_workers_on_a_tar_says_nothing_when_it_was_not_passed(tree, tmp_path, caplog):
    archive = compress_folder(tree, tmp_path / "q.tar.gz", format="tar.gz", fsync=False)

    with caplog.at_level("WARNING", logger="pytrove._archive_tools"):
        extract_archive(archive, tmp_path / "qx")

    assert "workers" not in caplog.text


def test_the_ceilings_count_what_is_written_not_what_the_archive_holds(tmp_path):
    # The filter runs before the budget, so a member nobody asked for costs
    # nothing against max_total_size.
    arc = tmp_path / "mix.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("small.py", "y" * 100)
        zf.writestr("big.bin", "z" * 500000)

    with pytest.raises(ArchiveLimitError):
        extract_archive(arc, tmp_path / "m1", limits=ArchiveLimits(max_total_size=1000))

    assert _extracted_into(arc, tmp_path / "m2", include="*.py",
                           limits=ArchiveLimits(max_total_size=1000)) == ["small.py"]

# --- what a member is compressed with, and whether it is readable at all ---

@pytest.mark.parametrize("method", ["ZIP_STORED", "ZIP_DEFLATED", "ZIP_BZIP2", "ZIP_LZMA"])
def test_every_zip_method_comes_back_as_itself(tmp_path, method):
    # This used to lift the compressed bytes out of the file and inflate
    # them by hand, which knew about deflate and nothing else: a bz2 or
    # lzma member was written to disk still compressed, under the right
    # name, with nothing said about it.
    payload = b"the real content, at a length worth compressing " * 40
    arc = tmp_path / f"{method}.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr(zipfile.ZipInfo("m.txt"), payload,
                    compress_type=getattr(zipfile, method))

    dest = tmp_path / "out"
    extract_archive(arc, dest)

    assert (dest / "m.txt").read_bytes() == payload


def _encrypted_zip(path):
    """A zip whose member is flagged encrypted, without needing a writer.

    zipfile reads the traditional scheme and cannot write it, so the flag
    is set by hand in both headers. What is under test is the branch that
    refuses to write an encrypted member as though it were plaintext, and
    that branch is reached by the flag.
    """

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("secret.txt", "the real secret content")

    blob = bytearray(path.read_bytes())
    blob[blob.find(b"PK\x03\x04") + 6] |= 1
    blob[blob.find(b"PK\x01\x02") + 8] |= 1
    path.write_bytes(bytes(blob))

    return path


def test_an_encrypted_member_is_not_written_as_ciphertext(tmp_path):
    arc = _encrypted_zip(tmp_path / "enc.zip")

    with pytest.raises(ValidationError, match="encrypted"):
        extract_archive(arc, tmp_path / "e1")

    with pytest.raises(ValidationError, match="[Bb]ad password"):
        extract_archive(arc, tmp_path / "e2", password="wrong")


@pytest.mark.skipif(shutil.which("zip") is None, reason="needs the zip command")
def test_a_password_extracts_a_zipcrypto_archive(tmp_path):
    plain = tmp_path / "a.txt"
    plain.write_text("password protected")
    arc = tmp_path / "pw.zip"

    subprocess.run(["zip", "-q", "-P", "hunter2", "-j", str(arc), str(plain)], check=True)

    dest = tmp_path / "pw"
    extract_archive(arc, dest, password="hunter2")

    assert (dest / "a.txt").read_text() == "password protected"


def test_a_password_on_a_tar_is_reported_rather_than_ignored(tree, tmp_path, caplog):
    archive = compress_folder(tree, tmp_path / "p.tar.gz", format="tar.gz", fsync=False)

    with caplog.at_level("WARNING", logger="pytrove._archive_tools"):
        extract_archive(archive, tmp_path / "px", password="unused")

    assert "no encryption of its own" in caplog.text


# --- where the destination is, and what it already is ----------------------

@pytest.mark.parametrize("atomic", [False, True])
def test_a_destination_that_is_a_file_is_refused_either_way(tmp_path, atomic):
    # atomic=True stages elsewhere and renames, so without an explicit
    # check it was the careful branch that replaced the file with a
    # directory while the ordinary one refused.
    arc = tmp_path / "s.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("x.txt", "x")

    victim = tmp_path / f"victim{atomic}.txt"
    victim.write_text("precious")

    with pytest.raises(OSError):
        extract_archive(arc, victim, atomic=atomic)

    assert victim.read_text() == "precious"


# --- two members, one path -------------------------------------------------

@pytest.mark.parametrize("policy", ["overwrite", "skip", "error"])
def test_two_members_landing_on_one_path_meet_the_overwrite_policy(tmp_path, policy):
    # Neither name is a duplicate of the other and neither is on disk when
    # the other is judged, so keying the check on the member name let the
    # second through whatever the policy said.
    arc = tmp_path / "case.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("Readme.txt", "first")
        zf.writestr("README.TXT", "second")

    dest = tmp_path / f"c_{policy}"

    probe = tmp_path / "CaseProbe"
    probe.write_text("x")

    if not (tmp_path / "caseprobe").exists():
        # A case-sensitive filesystem keeps both, and there is no collision
        # to have a policy about.
        extract_archive(arc, dest, limits=ArchiveLimits(overwrite=policy))
        assert len(list(dest.iterdir())) == 2
        return

    if policy == "error":
        with pytest.raises(ArchivePolicyError, match="already exists"):
            extract_archive(arc, dest, limits=ArchiveLimits(overwrite=policy))
        return

    extract_archive(arc, dest, limits=ArchiveLimits(overwrite=policy))

    assert [p.read_text() for p in dest.iterdir()] == [
        "second" if policy == "overwrite" else "first"
    ]


# --- a setting that is not one of the settings -----------------------------

# --- what the ceilings count ----------------------------------------------

def test_max_files_counts_directories_and_links_too(tmp_path):
    # It bounds how many filesystem entries an archive may create, and a
    # million empty directories costs what a million empty files costs.
    arc = tmp_path / "mf.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("a/", "")
        zf.writestr("a/x.txt", "x")
        zf.writestr("b/", "")
        zf.writestr("b/y.txt", "y")

    with pytest.raises(ArchiveLimitError, match="members allowed"):
        extract_archive(arc, tmp_path / "m1", limits=ArchiveLimits(max_files=2))

    dest = tmp_path / "m2"
    extract_archive(arc, dest, limits=ArchiveLimits(max_files=4))

    assert sorted(p.name for p in dest.rglob("*")) == ["a", "b", "x.txt", "y.txt"]


# --- a name is refused, never repaired ------------------------------------

def _tar_header(name, size=2):
    """One ustar header block, so a name can be put in it verbatim.

    tarfile normalises what it writes, which is the opposite of what these
    need: the point is a header that really does carry a leading slash.
    """

    b = bytearray(512)
    b[0:len(name)] = name.encode()
    b[100:108] = b"0000644\x00"
    b[108:116] = b"0000000\x00"
    b[116:124] = b"0000000\x00"
    b[124:136] = b"%011o\x00" % size
    b[136:148] = b"%011o\x00" % 0
    b[148:156] = b" " * 8
    b[156:157] = b"0"
    b[257:263] = b"ustar\x00"
    b[263:265] = b"00"
    b[148:156] = b"%06o\x00 " % sum(b)

    return bytes(b)


ABSOLUTE = ["/abs.txt", "//srv/abs.txt", "C:/win.txt", "..\\up.txt", "a/../../out.txt"]


def test_an_absolute_name_in_a_tar_is_refused_not_stripped(tmp_path):
    # Stripping the leading separator is what tar does and it is a silent
    # repair: the member arrives as "etc/passwd" and is written, having
    # never reached the check that refuses an absolute name.
    raw = b"".join(_tar_header(n) + b"xx" + bytes(510) for n in ABSOLUTE + ["ok.txt"])
    arc = tmp_path / "abs.tar.gz"
    arc.write_bytes(gzip.compress(raw + bytes(1024)))

    dest = tmp_path / "ax"
    extract_archive(arc, dest)

    assert sorted(str(p.relative_to(dest)) for p in dest.rglob("*")) == ["ok.txt"]


def test_an_absolute_name_in_a_zip_is_refused_not_stripped(tmp_path):
    arc = tmp_path / "abs.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        for name in ABSOLUTE + ["sub/ok.txt"]:
            zf.writestr(name, "x")

    dest = tmp_path / "zx"
    extract_archive(arc, dest)

    assert (sorted(str(p.relative_to(dest)).replace(os.sep, "/")
                   for p in dest.rglob("*")) == ["sub", "sub/ok.txt"])


# --- when a name is resolved, relative to when the ones before it landed ---

def test_a_name_is_resolved_after_the_members_ahead_of_it_are_written(tmp_path):
    # A symlink member changes where every name below it resolves to, so
    # deciding all the paths first and writing afterwards is exactly the
    # window a Zip Slip through a planted link needs.
    order = []
    real_place = internals._Extractor._place
    real_link = internals._Extractor._link

    def spy_place(self, m):
        order.append(("resolve", m.name))
        return real_place(self, m)

    def spy_link(self, m, target):
        order.append(("link", m.name))
        return real_link(self, m, target)

    arc = tmp_path / "seq.tar.gz"

    with tarfile.open(arc, "w:gz") as tf:
        link = tarfile.TarInfo("sub")
        link.type, link.linkname = tarfile.SYMTYPE, "../../outside"
        tf.addfile(link)
        info = tarfile.TarInfo("sub/evil.txt")
        info.size = 4
        tf.addfile(info, io.BytesIO(b"evil"))

    dest = tmp_path / "sx"

    try:
        internals._Extractor._place = spy_place
        internals._Extractor._link = spy_link
        extract_archive(arc, dest, limits=ArchiveLimits.permissive())
    finally:
        internals._Extractor._place = real_place
        internals._Extractor._link = real_link

    assert order == [("resolve", "sub"), ("link", "sub"),
                     ("resolve", "sub/evil.txt")]
    assert not (tmp_path / "outside").exists()
    assert (dest / "sub" / "evil.txt").read_bytes() == b"evil"


# --- memory, which is a correctness property on a large member -------------

def test_a_large_member_is_streamed_rather_than_held(tmp_path):
    # Holding the compressed blob and the inflated result at once cost
    # 89 MB on a 40 MB member. It is now bounded by one copy buffer.
    src = tmp_path / "big"
    src.mkdir()
    (src / "big.bin").write_bytes(os.urandom(1 << 20) * 24)
    arc = compress_folder(src, tmp_path / "big.zip", fsync=False)

    tracemalloc.start()

    try:
        extract_archive(arc, tmp_path / "bx")
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert peak < 8 << 20, f"{peak / 1e6:.1f} MB held for a 24 MB member"


# --- workers is one argument, read the same way on both formats ------------

@pytest.mark.parametrize("bad", ["4", True, 2.5])
def test_extraction_refuses_a_workers_value_it_cannot_read(tree, tmp_path, bad):
    # ZIP is the only format that uses the argument, so it is the only one
    # that judges it. On a tar the same value is ignored along with every
    # other -- see test_workers_on_a_tar_is_ignored_and_said_so.
    archive = compress_folder(tree, tmp_path / "w.zip", fsync=False)

    with pytest.raises(ValidationError, match="count or an executor"):
        extract_archive(archive, tmp_path / f"wx_{bad}", workers=bad)


def test_extraction_takes_a_pool_it_does_not_own(tree, tmp_path):
    archive = compress_folder(tree, tmp_path / "e.zip", fsync=False)
    dest = tmp_path / "ex"

    with ThreadPoolExecutor(3) as pool:
        extract_archive(archive, dest, workers=pool)

    assert (dest / "sub" / "deep" / "d.txt").read_bytes() == b"d"


# --- an archive written into the tree it is archiving ----------------------

def test_the_self_exclusion_takes_out_the_archive_and_nothing_else(tmp_path):
    # "backup.zip" as a bare name matched every file called that at any
    # depth, and the temp-file rule without its directory and its ".tmp"
    # suffix took out anything the user kept beside it under a leading dot.
    src = tmp_path / "tree"
    (src / "sub").mkdir(parents=True)
    (src / "notes").mkdir()
    (src / "keep.txt").write_text("keep")
    (src / "sub" / "backup.zip").write_bytes(b"an unrelated archive")
    (src / ".backup.zip.notes").write_text("a user file that only looks like a temp")
    (src / "notes" / ".backup.zip.readme").write_text("another")

    archive = compress_folder(src, src / "backup.zip", exclude_hidden=False, fsync=False)

    assert _names(archive) == {"keep.txt", "sub/backup.zip", ".backup.zip.notes",
                               "notes/.backup.zip.readme"}

    sizes = [compress_folder(src, src / "backup.zip", exclude_hidden=False,
                             fsync=False).stat().st_size for _ in range(3)]

    assert len(set(sizes)) == 1, f"the archive grew each run: {sizes}"

# --- how wide the tree may get, as against how deep ------------------------

def _zip_of(path, names, listed_dirs=()):
    with zipfile.ZipFile(path, "w") as zf:
        for d in listed_dirs:
            zf.writestr(d, "")
        for name in names:
            zf.writestr(name, "x")

    return path


def test_max_dir_entries_bounds_one_directory(tmp_path):
    arc = _zip_of(tmp_path / "flat.zip", [f"f{i}.txt" for i in range(5)])

    with pytest.raises(ArchiveLimitError, match="entries allowed"):
        extract_archive(arc, tmp_path / "a1", limits=ArchiveLimits(max_dir_entries=4))

    dest = tmp_path / "a2"
    extract_archive(arc, dest, limits=ArchiveLimits(max_dir_entries=5))

    assert len(list(dest.iterdir())) == 5


def test_max_dir_entries_counts_the_directories_a_path_implies(tmp_path):
    # An archive listing "a/b/c.txt" and nothing else still creates "a" and
    # "a/b", and each is an entry in its parent. Counting only the members
    # the archive troubled to name would leave a tree that is one entry per
    # level looking like three entries in the destination.
    arc = _zip_of(tmp_path / "deep.zip", ["a/b/c.txt"])

    extract_archive(arc, tmp_path / "d1", limits=ArchiveLimits(max_dir_entries=1))

    assert (tmp_path / "d1" / "a" / "b" / "c.txt").read_text() == "x"


def test_max_dir_entries_does_not_count_a_listed_directory_twice(tmp_path):
    # "a/" as a member of its own and "a/f1.txt" both register "a"; only the
    # first registration is an entry in the root.
    arc = _zip_of(tmp_path / "both.zip", ["a/f1.txt", "a/f2.txt"], listed_dirs=["a/"])

    dest = tmp_path / "b1"
    extract_archive(arc, dest, limits=ArchiveLimits(max_dir_entries=2))

    assert sorted(p.name for p in (dest / "a").iterdir()) == ["f1.txt", "f2.txt"]


def test_max_dir_entries_is_breadth_where_max_files_is_the_total(tmp_path):
    # 12 files, three to a directory, four directories in the root. The
    # widest directory is the root at four; the whole archive is sixteen
    # entries. Each ceiling refuses at its own number and neither stands in
    # for the other.
    arc = _zip_of(tmp_path / "spread.zip",
                  [f"d{i}/f{j}.txt" for i in range(4) for j in range(3)])

    with pytest.raises(ArchiveLimitError, match="entries allowed"):
        extract_archive(arc, tmp_path / "s1", limits=ArchiveLimits(max_dir_entries=3))

    with pytest.raises(ArchiveLimitError, match="members allowed"):
        extract_archive(arc, tmp_path / "s2", limits=ArchiveLimits(max_files=10))

    dest = tmp_path / "s3"
    extract_archive(arc, dest, limits=ArchiveLimits(max_dir_entries=4, max_files=16))

    assert len(list(dest.rglob("*.txt"))) == 12


def test_max_dir_entries_counts_what_survives_the_filter(tmp_path):
    # Same rule as every other ceiling: a member nobody asked for costs
    # nothing, so a directory is only as wide as what is being written.
    arc = _zip_of(tmp_path / "mix.zip", [f"f{i}.txt" for i in range(5)])

    dest = tmp_path / "f1"
    extract_archive(arc, dest, include="f0.txt", limits=ArchiveLimits(max_dir_entries=1))

    assert [p.name for p in dest.iterdir()] == ["f0.txt"]


@pytest.mark.parametrize("fmt", FORMATS)
def test_max_dir_entries_applies_to_every_format(tree, tmp_path, fmt):
    archive = compress_folder(tree, tmp_path / "w", format=fmt, fsync=False)

    with pytest.raises(ArchiveLimitError, match="entries allowed"):
        extract_archive(archive, tmp_path / f"wx_{fmt}", limits=ArchiveLimits(max_dir_entries=1))

# --- a directory check of the caller's own ---------------------------------

@pytest.fixture
def two_branches(tmp_path):
    """An archive with a keep/ and a drop/ branch, each two levels deep."""

    arc = tmp_path / "branches.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        for name in ("keep/a.txt", "keep/deep/b.txt",
                     "drop/c.txt", "drop/deep/d.txt", "top.txt"):
            zf.writestr(name, "x" * 100)

    return arc


def _landed(dest):
    return sorted(str(p.relative_to(dest)).replace(os.sep, "/")
                  for p in dest.rglob("*"))


def _recorder(verdict=lambda rel: None):
    """Record each directory by its position in the tree, and answer.

    dir_check is handed an absolute path under a staging directory, so the
    tree-relative name has to be worked out. The walk is outermost first
    and every top-level directory's parent is the root, so the first call
    fixes it.
    """

    seen, root = [], []

    def check(path):
        if not root:
            root.append(path.parent)

        rel = str(path.relative_to(root[0])).replace(os.sep, "/")
        seen.append(rel)

        return verdict(rel)

    return check, seen


def test_dir_check_is_handed_the_directory_with_its_contents_in_it(two_branches, tmp_path):
    # The whole point of running after the members are written: a check
    # that could only see a name could not have asked any of this.
    inside = {}

    def check(path):
        inside[path.name] = sorted(p.name for p in path.iterdir())

    dest = tmp_path / "p0"
    extract_archive(two_branches, dest, limits=ArchiveLimits(dir_check=check))

    assert inside["keep"] == ["a.txt", "deep"]
    assert inside["drop"] == ["c.txt", "deep"]
    assert sorted(inside["deep"]) in (["b.txt"], ["d.txt"])
    assert _landed(dest) == ["drop", "drop/c.txt", "drop/deep", "drop/deep/d.txt",
                             "keep", "keep/a.txt", "keep/deep", "keep/deep/b.txt",
                             "top.txt"]


def test_dir_check_drops_the_subtree_it_refuses(two_branches, tmp_path):
    check, asked = _recorder(lambda rel: rel != "drop")

    dest = tmp_path / "p1"
    extract_archive(two_branches, dest, limits=ArchiveLimits(dir_check=check))

    assert _landed(dest) == ["keep", "keep/a.txt", "keep/deep",
                             "keep/deep/b.txt", "top.txt"]
    # "drop/deep" is never asked about: a refusal is not descended into.
    assert sorted(asked) == ["drop", "keep", "keep/deep"]


def test_dir_check_sees_every_directory_once_listed_or_not(two_branches, tmp_path):
    # The archive names no directory members at all, so all four of these
    # are directories a member's path implies. Returning None is the same
    # as approving, which is what a check written only to raise does.
    check, calls = _recorder()

    dest = tmp_path / "p2"
    extract_archive(two_branches, dest, limits=ArchiveLimits(dir_check=check))

    assert sorted(calls) == ["drop", "drop/deep", "keep", "keep/deep"]
    assert len(_landed(dest)) == 9


def test_dir_check_is_asked_about_an_empty_directory_member(tmp_path):
    arc = tmp_path / "lonely.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("lonely/", "")

    asked = []
    dest = tmp_path / "p3"
    extract_archive(arc, dest, limits=ArchiveLimits(
        dir_check=lambda p: asked.append(p.name) or False))

    assert asked == ["lonely"]
    assert _landed(dest) == []


@pytest.mark.parametrize("atomic", [False, True])
def test_dir_check_may_raise_and_the_exception_is_the_callers(two_branches, tmp_path, atomic):
    class Unacceptable(RuntimeError):
        pass

    def check(path):
        if path.name == "drop":
            raise Unacceptable(f"{path.name!r} is not acceptable")

    dest = tmp_path / f"p4_{atomic}"

    with pytest.raises(Unacceptable, match="not acceptable"):
        extract_archive(two_branches, dest, atomic=atomic,
                        limits=ArchiveLimits(dir_check=check))

    # A dir_check always stages, so the raise takes the whole tree with it
    # whatever `atomic` said, and nothing reaches the destination.
    assert not dest.exists() or _landed(dest) == []
    assert not list(tmp_path.glob(".*.tmp"))


def test_dir_check_does_not_delete_what_was_already_in_the_destination(two_branches, tmp_path):
    # Dropping a directory means removing it after it was written. Done in
    # `dest` that would take anything already living under the same name
    # with it -- which is why a dir_check stages whatever `atomic` says.
    dest = tmp_path / "p5"
    (dest / "drop").mkdir(parents=True)
    (dest / "drop" / "mine.txt").write_text("mine")

    check, _ = _recorder(lambda rel: rel != "drop")
    extract_archive(two_branches, dest, limits=ArchiveLimits(dir_check=check))

    assert (dest / "drop" / "mine.txt").read_text() == "mine"
    assert not (dest / "drop" / "c.txt").exists()
    assert (dest / "keep" / "a.txt").exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_dir_check_now_runs_after_the_ceilings_have_counted(two_branches, tmp_path):
    # It used to run during the walk, so a refused branch was never
    # counted. Seeing inside a directory means it has to be written first,
    # and what is written is weighed -- refusing it afterwards does not
    # give the budget back.
    check, _ = _recorder(lambda rel: not rel.startswith("drop"))

    with pytest.raises(ArchiveLimitError, match="expands past"):
        extract_archive(two_branches, tmp_path / "p6", limits=ArchiveLimits(
            max_total_size=350, dir_check=check))

    assert not list(tmp_path.glob(".*.tmp"))


def test_dir_check_is_not_bothered_about_what_exclude_already_dropped(two_branches, tmp_path):
    # exclude still prunes before anything is read, so an excluded branch
    # is never extracted and therefore never there to be asked about.
    check, asked = _recorder()

    extract_archive(two_branches, tmp_path / "p7", exclude="drop",
                    limits=ArchiveLimits(dir_check=check))

    assert sorted(asked) == ["keep", "keep/deep"]


def test_dir_check_works_on_a_tar_as_well(tmp_path):
    arc = tmp_path / "b.tar.gz"

    with tarfile.open(arc, "w:gz") as tf:
        for name in ("keep/a.txt", "drop/c.txt"):
            info = tarfile.TarInfo(name)
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))

    dest = tmp_path / "p8"
    extract_archive(arc, dest, limits=ArchiveLimits(
        dir_check=lambda p: p.name != "drop"))

    assert _landed(dest) == ["keep", "keep/a.txt"]


def test_a_dir_check_that_is_not_callable_fails_at_the_first_call(tmp_path):
    # Not checked up front: Optional[Callable] says it, and calling a str
    # says it again, at once and in the caller's own traceback.
    arc = tmp_path / "v.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("a/x.txt", "x")

    with pytest.raises(TypeError, match="not callable"):
        extract_archive(arc, tmp_path / "p9", limits=ArchiveLimits(dir_check="nope"))

# --- a raw string is a working policy, not just an accepted one ------------
#
# Nothing normalises a policy any more, so whatever the caller typed is what
# every comparison in the extractor sees. These pin that down by running the
# same extraction twice -- once with the string, once with the enum member --
# and demanding the same outcome. What they guard against is one character:
# an `is` where an `==` belongs, which no other test in this file would catch.

def _corrupt_zip(path):
    """A zip whose member fails its CRC, with the declared size intact."""

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("a.txt", "hello")

    blob = bytearray(path.read_bytes())
    blob[blob.index(b"hello")] = ord("H")
    path.write_bytes(bytes(blob))

    return path


@pytest.mark.parametrize("policy", ["overwrite", "skip", "error"])
def test_a_raw_overwrite_string_picks_the_same_branch_as_its_enum(tmp_path, policy):
    # "overwrite" is the discriminating one: under `is` the raw string fails
    # the identity test, falls into the collision branch it was meant to
    # skip, and quietly leaves the old file in place.
    arc = tmp_path / f"o_{policy}.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("a.txt", "new")

    member = pytrove.enums.ArchiveOverwritePolicy(policy)

    def outcome(limits, tag):
        dest = tmp_path / f"{policy}_{tag}"
        dest.mkdir()
        (dest / "a.txt").write_text("old")

        try:
            extract_archive(arc, dest, limits=limits)
        except ArchivePolicyError:
            return "refused"

        return (dest / "a.txt").read_text()

    assert outcome(ArchiveLimits(overwrite=policy), "raw") == outcome(
        ArchiveLimits(overwrite=member), "enum")


@pytest.mark.parametrize("policy", ["skip", "error"])
def test_a_raw_duplicates_string_picks_the_same_branch_as_its_enum(tmp_path, policy):
    arc = tmp_path / f"d_{policy}.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("a.txt", "first")
        zf.writestr("a.txt", "second")

    member = pytrove.enums.ArchiveDuplicatePolicy(policy)

    def outcome(limits, tag):
        dest = tmp_path / f"dup_{policy}_{tag}"

        try:
            extract_archive(arc, dest, limits=limits)
        except ArchivePolicyError:
            return "refused"

        return (dest / "a.txt").read_text()

    assert outcome(ArchiveLimits(duplicates=policy), "raw") == outcome(
        ArchiveLimits(duplicates=member), "enum")


@pytest.mark.parametrize("policy", ["allow", "skip", "error"])
def test_a_raw_symlinks_string_picks_the_same_branch_as_its_enum(tmp_path, caplog, policy):
    # What lands on disk cannot tell these apart everywhere: creating a
    # symlink needs a privilege an ordinary Windows account does not hold,
    # so "allow" and "skip" both end with no link there. The log does tell
    # them apart -- one says the policy skipped it, the other says the
    # platform refused it -- so that is what is compared.
    arc = _tar_of(tmp_path, [("real.txt", "file", b"r", None),
                             ("in.lnk", "sym", None, "real.txt")])
    member = pytrove.enums.ArchiveLinkPolicy(policy)

    def outcome(limits, tag):
        dest = tmp_path / f"sym_{policy}_{tag}"
        caplog.clear()

        with caplog.at_level("WARNING", logger="pytrove._archive_tools"):
            try:
                extract_archive(arc, dest, limits=limits)
                landed = sorted(p.name for p in dest.rglob("*"))
            except ArchivePolicyError:
                landed = "refused"

        return landed, "skipped symlink member" in caplog.text

    assert outcome(ArchiveLimits(symlinks=policy), "raw") == outcome(
        ArchiveLimits(symlinks=member), "enum")


def _zeros_targz(path, size):
    with tarfile.open(path, "w:gz") as tf:
        info = tarfile.TarInfo("big.bin")
        info.size = size
        tf.addfile(info, io.BytesIO(b"\0" * size))

    return path


def test_max_ratio_does_not_bound_a_tar_and_max_total_size_does(tmp_path):
    # max_ratio needs a per-member compressed size, and a tar records
    # none -- the whole stream is one unit. So it is skipped there, and
    # this pins that rather than pretending otherwise: on a tar the
    # absolute ceilings are the bomb check.
    arc = _zeros_targz(tmp_path / "bomb.tar.gz", 8 << 20)

    assert arc.stat().st_size * 1000 < (8 << 20)      # a real ratio over 1000

    extract_archive(arc, tmp_path / "through",
                    limits=ArchiveLimits(max_ratio=1.0001))
    assert (tmp_path / "through" / "big.bin").stat().st_size == (8 << 20)

    with pytest.raises(ArchiveLimitError, match="expands past"):
        extract_archive(arc, tmp_path / "no",
                        limits=ArchiveLimits(max_total_size=1 << 20))


def test_max_ratio_bounds_a_zip_from_its_header(tmp_path):
    arc = tmp_path / "bomb.zip"

    with zipfile.ZipFile(arc, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.bin", b"\0" * (8 << 20))

    with pytest.raises(ArchiveLimitError, match="expands"):
        extract_archive(arc, tmp_path / "no", limits=ArchiveLimits(max_ratio=100))

    # refused from the header, so nothing was written at all
    assert not (tmp_path / "no").exists() or not list((tmp_path / "no").iterdir())

    extract_archive(arc, tmp_path / "ok", limits=ArchiveLimits(max_ratio=100_000))
    assert (tmp_path / "ok" / "big.bin").stat().st_size == (8 << 20)


def test_atomic_leaves_nothing_behind_when_a_running_ceiling_trips(tmp_path):
    # max_file_size is re-weighed against what is actually written, so it
    # can only refuse once part of the member is down.
    arc = _zeros_targz(tmp_path / "big.tar.gz", 8 << 20)
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "mine.txt").write_text("mine")

    with pytest.raises(ArchiveLimitError):
        extract_archive(arc, dest, atomic=True,
                        limits=ArchiveLimits(max_file_size=1 << 20))

    assert sorted(p.name for p in dest.iterdir()) == ["mine.txt"]
    assert not list(tmp_path.glob(".*.tmp"))


def test_a_member_that_does_not_produce_what_it_declares_is_refused(tmp_path):
    whole = _zeros_targz(tmp_path / "whole.tar.gz", 8 << 20)
    raw = whole.read_bytes()

    cut = tmp_path / "cut.tar.gz"
    cut.write_bytes(raw[:len(raw) // 3])

    with pytest.raises(ValidationError, match="ends before"):
        extract_archive(cut, tmp_path / "out")


def test_an_honest_archive_still_extracts_byte_for_byte(tmp_path):
    src = tmp_path / "tree"
    (src / "lib").mkdir(parents=True)
    (src / "a.txt").write_text("hello" * 1000)
    (src / "empty.txt").write_text("")
    blob = os.urandom(1 << 20)
    (src / "lib" / "b.bin").write_bytes(blob)

    for fmt in ("zip", "tar.gz"):
        arc = compress_folder(src, tmp_path / f"ok.{fmt}", format=fmt)
        dest = tmp_path / f"out-{fmt}"
        extract_archive(arc, dest)

        assert (dest / "a.txt").read_text() == "hello" * 1000
        assert (dest / "empty.txt").read_bytes() == b""
        assert (dest / "lib" / "b.bin").read_bytes() == blob


def test_a_directory_is_only_put_to_enter_once(tmp_path):
    # _ancestry memoises what enter() said about one directory. Keyed on
    # the whole branch instead, "t/a/b" and "t/a" and "t" were three
    # unrelated entries each re-walking from the root to build itself.
    arc = tmp_path / "deep.zip"
    names = []

    for t in range(6):
        for a in range(3):
            for b in range(3):
                names += [f"t{t}/f.txt", f"t{t}/a{a}/f.txt",
                          f"t{t}/a{a}/b{b}/f{b}.txt",
                          f"t{t}/a{a}/b{b}/c/f{b}.txt"]

    with zipfile.ZipFile(arc, "w") as zf:
        for n in dict.fromkeys(names):
            zf.writestr(n, b"x")

    asked = []
    real_enter = internals._Filter.enter

    def spy(self, rel, entry=None):
        asked.append(rel)
        return real_enter(self, rel, entry)

    try:
        internals._Filter.enter = spy
        extract_archive(arc, tmp_path / "out", exclude="matches-nothing")
    finally:
        internals._Filter.enter = real_enter

    assert asked, "the filter was never consulted at all"
    assert len(asked) == len(set(asked)), (
        f"{len(asked) - len(set(asked))} directories were asked about twice")


def test_a_refused_directory_still_prunes_below_a_cached_ancestor(tmp_path):
    # The fast path reads _ancestry[head] and trusts it. That is only sound
    # because a directory is written into it after its ancestors answered
    # True, so finding one there is proof of the whole branch. This pins it:
    # "a/b" is reached and cached while keeping "a/b/drop" refused.
    arc = tmp_path / "mid.zip"

    with zipfile.ZipFile(arc, "w") as zf:
        for n in ("a/keep.txt", "a/b/keep.txt",
                  "a/b/drop/x.txt", "a/b/drop/deep/y.txt"):
            zf.writestr(n, b"x")

    dest = tmp_path / "mid"
    extract_archive(arc, dest, exclude="drop")

    assert _landed(dest) == ["a", "a/b", "a/b/keep.txt", "a/keep.txt"]


# ---------------------------------------------------------------------
# what `dest` is called is an answer, and `format` has to agree with it
# ---------------------------------------------------------------------

@pytest.mark.parametrize("name, fmt", [
    ("out.zip", ArchiveFormat.ZIP),
    ("out.tar.gz", ArchiveFormat.TAR_GZ),
    ("out.tgz", ArchiveFormat.TAR_GZ),
] + ([("out.tar.zst", ArchiveFormat.TAR_ZST)] if HAS_ZSTD else []))
def test_the_format_is_read_off_the_destination_name(tree, tmp_path, name, fmt):
    # format defaults to None, which means "the name already said it".
    # Checked against the archive's leading bytes rather than against its
    # extension, since the extension is the thing under test.
    made = compress_folder(tree, tmp_path / name, fsync=False)

    assert made.name == name
    assert _Extractor.detect_format(str(made)) is fmt


def test_a_destination_directory_falls_back_to_zip(tree, tmp_path):
    # A directory has no extension to read, so there is nothing to derive
    # from and the old default stands.
    out = tmp_path / "out"
    out.mkdir()

    made = compress_folder(tree, out, fsync=False)

    assert made.name == "src.zip"
    assert _Extractor.detect_format(str(made)) is ArchiveFormat.ZIP


def test_an_extension_that_says_nothing_is_refused_rather_than_guessed(tree, tmp_path):
    # Guessing here is how a zip ends up called backup.tar.gz, which is
    # the mistake reading the name is there to catch.
    with pytest.raises(ValidationError, match="cannot tell what format"):
        compress_folder(tree, tmp_path / "backup.bin", fsync=False)

    assert not (tmp_path / "backup.bin").exists()


def test_a_format_that_disagrees_with_the_name_is_refused(tree, tmp_path):
    with pytest.raises(ValidationError, match="does not match"):
        compress_folder(tree, tmp_path / "backup.tar.gz",
                        format=ArchiveFormat.ZIP, fsync=False)

    assert not (tmp_path / "backup.tar.gz").exists()


def test_a_format_that_agrees_with_the_name_is_not_a_disagreement(tree, tmp_path):
    # Passing both is allowed; they only have to say the same thing. The
    # raw string spelling is the one a caller is likeliest to reach for.
    made = compress_folder(tree, tmp_path / "b.tgz", format="tar.gz", fsync=False)

    assert _Extractor.detect_format(str(made)) is ArchiveFormat.TAR_GZ


def test_an_unknown_extension_cannot_disagree_with_an_explicit_format(tree, tmp_path):
    # An extension this does not recognise says nothing, and something
    # that says nothing cannot contradict anything.
    made = compress_folder(tree, tmp_path / "backup.bin",
                           format=ArchiveFormat.ZIP, fsync=False)

    assert made.name == "backup.bin"
    assert _Extractor.detect_format(str(made)) is ArchiveFormat.ZIP


def test_an_archive_that_cannot_be_identified_is_a_util_error(tmp_path):
    # Every refusal this library raises is a UtilError, so one except
    # clause covers them. ValidationError is also a ValueError, so code
    # that already caught that keeps working.
    junk = tmp_path / "mystery.bin"
    junk.write_bytes(b"not an archive at all")

    with pytest.raises(pytrove.errors.UtilError, match="cannot tell what format"):
        extract_archive(junk, tmp_path / "dest")


# ---------------------------------------------------------------------
# a directory is never taken by something that is not one
# ---------------------------------------------------------------------

@pytest.mark.parametrize("atomic", [False, True])
@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_a_member_never_takes_the_path_a_directory_holds(tmp_path, atomic, kind, caplog):
    # The rule _link states, and the reason _graft has to repeat it: under
    # `atomic` the link is written into an empty staging tree, where
    # nothing is standing in the way, so the two sides only meet at the
    # merge. Before that they disagreed -- the staged path removed the
    # caller's directory and everything in it, silently.
    dest = tmp_path / "dest"
    (dest / "keepme" / "deep").mkdir(parents=True)
    (dest / "keepme" / "precious.txt").write_text("precious")

    archive = tmp_path / "clash.zip"

    with zipfile.ZipFile(archive, "w") as zf:
        if kind == "symlink":
            if not _can_symlink(tmp_path):
                pytest.skip("cannot create a symlink here")

            info = zipfile.ZipInfo("keepme")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "real.txt")
        else:
            zf.writestr("keepme", "I am not a directory")

        zf.writestr("real.txt", "real")

    with caplog.at_level("WARNING"):
        extract_archive(archive, dest, atomic=atomic,
                        limits=ArchiveLimits(symlinks="allow"))

    assert (dest / "keepme").is_dir() and not (dest / "keepme").is_symlink()
    assert (dest / "keepme" / "precious.txt").read_text() == "precious"
    assert (dest / "keepme" / "deep").is_dir()
    # the rest of the archive is unaffected -- one refused member does not
    # cost the others
    assert (dest / "real.txt").read_text() == "real"
    # Said out loud, in whichever of the three voices refused it: _link
    # and _graft both name the directory, and a plain file written
    # straight into an existing destination is stopped by the open() in
    # _spill and reports what the filesystem said.
    assert "keepme" in caplog.text


# ---------------------------------------------------------------------
# the commit clears nothing to make room
# ---------------------------------------------------------------------

@pytest.mark.parametrize("present", [False, True])
def test_a_commit_that_cannot_finish_keeps_both_sides(tmp_path, monkeypatch, caplog, present):
    # The destination used to be removed first so that os.replace could
    # rename onto it. A replace that then failed left the caller with
    # neither the directory nor the archive. Nothing is cleared now, so a
    # failed commit costs nothing that was there and loses nothing that
    # came out.
    dest = tmp_path / "dest"

    if present:
        dest.mkdir()
        (dest / "mine.txt").write_text("mine")

    archive = tmp_path / "a.zip"

    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.txt", "A")

    real = os.replace

    def refuse(src, target, *args, **kwargs):
        # Every write into the destination fails: the one rename when it
        # is not there, and the per-member moves of the merge when it is.
        landing = os.fspath(target)

        if landing == str(dest) or landing.startswith(str(dest) + os.sep):
            raise PermissionError("refused for the test")

        return real(src, target, *args, **kwargs)

    monkeypatch.setattr(os, "replace", refuse)

    with caplog.at_level("ERROR"):
        with pytest.raises(PermissionError):
            extract_archive(archive, dest, atomic=True)

    assert dest.exists() is present

    if present:
        assert (dest / "mine.txt").read_text() == "mine"

    # what came out of the archive is still on disk, and the log says where
    staged = [p for p in tmp_path.iterdir()
              if p.name.startswith(".dest.") and p.name.endswith(".tmp")]

    assert len(staged) == 1
    assert (staged[0] / "a.txt").read_text() == "A"
    # the name, not the whole path: the log writes it with %r, which
    # doubles every separator on Windows
    assert staged[0].name in caplog.text


# ---------------------------------------------------------------------
# a level of nesting costs the filesystem, never a stack frame
# ---------------------------------------------------------------------

def _can_symlink(tmp_path):
    """Whether this account may create a symlink at all.

    Windows refuses one without SeCreateSymbolicLinkPrivilege, which an
    ordinary account does not hold and Developer Mode grants. Asked rather
    than assumed, since the same machine can answer either way.
    """

    probe = tmp_path / f".symlink_probe_{os.getpid()}"

    try:
        probe.symlink_to(tmp_path)
    except (OSError, NotImplementedError):
        return False

    probe.unlink()

    return True


@contextlib.contextmanager
def _tight_stack(headroom):
    """Leave `headroom` frames, so anything recursing per level trips.

    Cheaper and far more portable than nesting a real tree past the
    interpreter's limit: 1000 levels of even one-character names is past
    what Windows takes without long paths on and past PATH_MAX on Linux,
    so the depth that would prove it cannot be written to disk anywhere.
    Lowering the ceiling to meet a shallow tree asks the same question.
    """

    n, frame = 0, sys._getframe()

    while frame is not None:
        n += 1
        frame = frame.f_back

    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(n + headroom)

    try:
        yield
    finally:
        sys.setrecursionlimit(limit)


#: Deep enough that one frame per level would need three times the
#: headroom below, and short enough that the path fits on Windows without
#: long paths enabled.
_NESTED = 60
_CHAIN = "/".join("a" for _ in range(_NESTED))


def test_a_deep_archive_is_written_without_one_frame_per_level(tmp_path):
    # _mkdir walks up and creates bottom-up in two loops, in place of
    # mkdir(parents=True), which recurses once per missing level inside
    # pathlib -- measured, an archive nesting 1500 directories raised
    # RecursionError out of the standard library, from a path the caller
    # never chose.
    #
    # atomic=False, because the commit ends in remove_path and that is
    # shutil.rmtree, which recurses once per directory on everything
    # before 3.14. The merge is measured on its own below, where the
    # removal is not in the way.
    archive = tmp_path / "deep.zip"

    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(f"{_CHAIN}/leaf.txt", "leaf")

    dest = tmp_path / "dest"
    dest.mkdir()

    with _tight_stack(30):
        extract_archive(archive, dest, atomic=False)

    assert (dest.joinpath(*(["a"] * _NESTED)) / "leaf.txt").read_text() == "leaf"


def test_the_merge_walks_with_a_stack_and_not_with_frames(tmp_path):
    # _graft used to recurse once per level. Measured directly rather
    # than through a tight stack: the frame depth at each level of the
    # walk is recorded, and a walk that descends on an explicit stack
    # stays flat where one that recurses grows by a frame a level.
    #
    # _is_dir is the probe because _graft is the only thing that
    # calls it, once per entry it looks at.
    depths = []
    real = internals._is_dir

    def watching(path):
        n, frame = 0, sys._getframe()

        while frame is not None:
            n += 1
            frame = frame.f_back

        depths.append(n)

        return real(path)

    levels = 12
    chain = "/".join("a" for _ in range(levels))
    archive = tmp_path / "nested.zip"

    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(f"{chain}/leaf.txt", "leaf")

    # The destination is given the same chain, so every level of it is a
    # directory on both sides and the merge has to descend rather than
    # moving the top across in one step.
    dest = tmp_path / "dest"
    here = dest

    for _ in range(levels + 1):
        here.mkdir()
        here = here / "a"

    bottom = dest.joinpath(*(["a"] * levels))
    (bottom / "keep.txt").write_text("keep")

    internals._is_dir = watching

    try:
        extract_archive(archive, dest, atomic=True)
    finally:
        internals._is_dir = real

    assert (bottom / "leaf.txt").read_text() == "leaf"
    assert (bottom / "keep.txt").read_text() == "keep"
    assert len(depths) > levels, "the merge never descended the chain"
    assert max(depths) - min(depths) <= 2, (
        f"the merge deepened the stack by {max(depths) - min(depths)} frames "
        f"over {levels} levels -- it is recursing"
    )
