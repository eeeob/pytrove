import os
import sys

from pathlib import Path
from typing import Optional, Union
from concurrent.futures import Executor

from .typings import ArchiveLimits, NestedContainer, PathLike
from .enums import ArchiveFormat
from .errors import ValidationError
from .iter_tools import iter_flat_cont, to_frozenset
from .files_tools import atomic_write, resolve_path
from ._archive_tools import (
    std_zstd,
    zstandard,
    _Compressor,
    _Extractor,
    _Filter,
    _Rule, 
)


def _is_hidden(_, entry: Optional[os.DirEntry]) -> bool:
    if entry is None:
        return False

    if entry.name.startswith("."):
        return True

    try:
        return bool(getattr(entry.stat(), "st_file_attributes", 0) & 0x2)
    except OSError:
        return False

def _temp_file_rule(folder: str, prefix: str):
    """Match only atomic_write's own temp file for one destination.

    It is written into the destination's directory as ".<name>.XXXXXXXX.tmp"
    -- see files_tools.atomic_write -- so all three parts are checked: the
    directory it must be in, the prefix, and the suffix. Checking the prefix
    alone was enough to drop a user's own ".backup.zip.notes", and to drop it
    from any directory in the tree.
    """

    cut = len(folder)

    def rule(rel: str, _entry) -> bool:
        if not rel.startswith(folder):
            return False

        base = rel[cut:]

        return ("/" not in base
                and base.startswith(prefix)
                and base.endswith(".tmp"))

    return rule


def _require_zstd() -> None:
    """Raise the standard missing-extra error unless zstd is available.

    Two backends can serve, and each is either the imported module or
    None: compression.zstd, which is standard library from 3.14, and the
    zstandard package. Either is enough, so the cure
    depends on why it is missing. On 3.14 the module is importable whenever
    Python was compiled against libzstd, so its absence there means the
    interpreter was built without it and the extra would fix nothing --
    pointing someone at `pip install` sends them after a package they do
    not need and leaves them stuck.
    """

    if std_zstd is not None or zstandard is not None:
        return

    if sys.version_info >= (3, 14):
        raise ImportError(
            "compress_folder: tar.zst needs zstd support, and this "
            "interpreter was built without it -- compression.zstd is part "
            "of the standard library from 3.14, but only when Python was "
            "compiled against libzstd. Either use an interpreter that was, "
            "or install the third-party backend: pip install zstandard"
        )

    raise ImportError(
        "To use this feature, all required packages must be installed.\n"
        "Run: pip install 'pytrove[zstd]'\n"
        "\n"
        "Required : 'zstandard'\n"
        "Missing  : 'zstandard'"
    )



def compress_folder(
    src: PathLike,
    dest: PathLike,
    *,
    format: Union[ArchiveFormat, str] = ArchiveFormat.ZIP,
    include: Optional[NestedContainer[_Rule]] = None,
    exclude: Optional[NestedContainer[_Rule]] = None,
    level: Optional[int] = None,
    workers: Optional[Union[int, Executor]] = None,
    follow_symlinks: bool = False,
    exclude_hidden: bool = True,
    fsync: bool = True,
    ) -> Path:

    """Archive the folder at `src` into `dest`, and return the archive path.

    `dest` may name the archive itself, or an existing directory to put it
    in -- in which case it is named after `src` with the format's extension.
    The archive is written through atomic_write, so an interrupted backup
    leaves no half-file behind and never replaces a previous archive with a
    truncated one.

    What gets archived is decided by one ladder, walked from the top.
    The first rung that matches is the whole answer -- nothing below it is
    consulted:

      1. `include`   a whole path      -> archive
      2. `exclude`   a whole path      -> skip
      3. `include`   a predicate       -> archive
      4. `exclude`   a predicate       -> skip
      5. `include`   a bare name       -> archive
      6. `exclude`   a bare name       -> skip
      7. `exclude`   a glob            -> skip
      8. `include`   a glob            -> archive

    There is one argument per side. Which rung a rule lands on is read off
    the rule itself, so nothing has to be declared:

      lambda p, e: .. a predicate. Any callable taking two arguments and
                      returning a bool: the path relative to `src`, and
                      the os.DirEntry it belongs to -- so a rule can ask
                      about the thing itself, its size or its mtime, and
                      not only about its name. It is handed directories as
                      well as files, so it can turn a whole subtree on or
                      off, and it is called once per entry in no
                      guaranteed order.

      "*.log"         a glob -- anything carrying "*", "?" or "[".
      "logs/*.tmp"    a "/" inside anchors it at `src`.

      "src/main.py"   a whole path, because it carries a path: it names
      "/logs"         one place. A leading "/" anchors to `src` and only
                      `src`, which is the same kind of statement.

      "logs"          a bare name, because it is only a name: it matches
                      any entry called that, at any depth.

    Each argument takes one item, a list, or any nesting of them, and
    every path is relative to `src` and written with "/".

    A rule is matched against one entry -- its own name, or its own path.
    It says nothing about what is inside it, and **the two sides are not
    symmetric about that**. It is the one thing here worth reading twice:

      `exclude` reaches downward. A directory it matches is pruned, so
      nothing inside is ever looked at. exclude="node_modules" empties the
      whole directory without a single rule matching the files in it --
      and no `include` reaches back in to rescue one, the same limitation
      gitignore documents, for the same reason.

      `include` does not. Every file is matched on its own path, and a
      directory matching changes nothing about what is under it. So

          include="sub"      archives nothing at all -- "sub" is a
                             directory, and no file's path equals it.
          include="sub/*"    archives sub/c.py but not sub/deep/d.txt --
                             "*" stops at the separator.
          include="sub/**"   archives the subtree, which is what "**" is
                             for and the only spelling that means it.

    The asymmetry is deliberate. Pruning is what makes an excluded subtree
    cost one check rather than a walk of everything in it, and that saving
    only exists because the verdict is final. `include` cannot prune --
    a match may lie any depth below -- so it has nothing to carry down and
    is left saying exactly what it says.

    The two sides interleave rather than one of them winning outright, and
    that is the point of the order. Naming a whole path or writing a
    predicate is a deliberate statement about one thing, so `include` gets
    to rescue it out of a broad exclusion -- as long as the exclusion did
    not name a directory above it, which is pruned before anything inside
    is seen:

        compress_folder(src, dest, exclude="*.json",
                        include="build/version.json")
        compress_folder(src, dest, exclude="*.tmp",
                        include=lambda p, e: e.stat().st_size < 4096)

    A glob is a blunt instrument on both sides, and there `exclude` goes
    first -- of the two ways to get a broad pattern wrong, leaving
    something out of an archive is the one you can fix by running it
    again.

    Globs are matched by `pathspec` when the `glob` extra is installed,
    which is the same engine git itself is modelled on. Without it they
    fall back to `fnmatch` from the standard library, and exactly three
    kinds of pattern then behave differently -- measured, not guessed:

      "**"      is not a segment wildcard under the fallback. It is two
                plain stars followed by a literal "/", so "**/logs" needs
                a slash to be there and silently misses a top-level
                logs/. Write "logs", which reaches every depth anyway.
      "/*.py"   does not anchor under the fallback. "*" spans "/" in
                fnmatch whatever precedes it, so a leading slash on a
                *glob* has no effect and src/x.py matches a pattern that
                asked for the root only.
      "sub/*"   is the direct children of sub with the extra, and every
                depth under it without -- the same cause as the anchor:
                "*" does not stop at a separator in fnmatch. "sub/**" is
                the whole subtree either way, so it is the spelling to
                reach for when the answer has to be the same everywhere.

    Nothing else differs. A bare glob reaches every depth and a glob with
    a "/" is anchored under both. And only globs are affected at all:
    bare names, whole paths and predicates are this library's own on
    either backend, so "/logs" -- a path, not a glob -- anchors correctly
    with or without the extra.

    If a filter has to mean the same thing on every machine, either
    require the extra or keep to the patterns above.

        pip install 'pytrove[glob]'

    An entry no rung matched is archived when there are no `include` rules
    at all, and skipped when there are: passing anything on the include
    side means "only what matches". So

        compress_folder(src, dest, include=["a.py", "docs/i.md"])

    archives exactly those two files.

    An excluded directory is pruned -- never descended into, so it costs
    one check rather than a walk of everything inside it. That is where an
    exclusion reaches the files under it: no rule has to match them, and
    none can rescue them either. `include` never prunes, since a match may
    lie any depth below.

    `exclude_hidden` is on by default and adds one more exclude predicate:
    anything whose name starts with a dot, plus whatever carries the hidden
    attribute on Windows. Being an ordinary rule, it prunes like one -- a
    hidden directory is not descended into, so a .git or .venv costs one
    check rather than a walk of everything inside it -- and it loses to the
    include rungs above it, so include="/.env" archives that file while the
    rest of the hidden entries stay out. Pass exclude_hidden=False to keep
    them all.

    `follow_symlinks` is off by default, and off means *left out*, not
    recorded as a link: neither of the archive formats written here stores
    one, so a symlink is skipped entirely and its target is not read.
    Turning it on archives what the link points at, as ordinary content, at
    the path the link occupies -- so a tree with several links to the same
    directory stores that directory once per link.

    Two things about it are worth knowing before relying on it:

      it does not govern a Windows junction. Python does not report one as
      a symlink at all -- os.DirEntry.is_symlink() is False for a junction
      and is_dir() is True -- so a junction is followed under either
      setting, and this argument cannot turn that off.

      there is no cycle check. A link, or a junction, that points at one of
      its own ancestors is walked until the operating system refuses to
      resolve the path -- about 63 levels on Windows. It terminates, but
      the archive holds everything under it once per level.

    Empty directories are left out too, and so is one whose entire contents
    were filtered away: a directory is recorded only when a file inside it
    is actually being archived. Extracting therefore reproduces the files
    and the paths they need, not the shape of the source tree.

    Writing the archive into the folder being archived is safe: when `dest`
    lands inside `src`, one further exclude predicate is added for the
    destination and the temp file it is written through. Without it an
    archive records itself mid-write, and backing up to the same name
    repeatedly grows the file every run. Being a predicate it sits at rung
    4, so an `include` whole path or predicate would still pull the archive
    into itself -- ask for that and you get it. Any *other* archive already
    sitting in the tree is ordinary content; add `exclude="*.zip"` (or the
    format you use) if you want those out too.

    `format` picks the container, see ArchiveFormat:

      ZIP (default)  every file compressed independently, which is the only
                     format here whose work can be split across threads.
      TAR_ZST        one stream, parallelised inside zstandard instead when
                     asked; reaches gzip's ratio several times faster.
                     Needs the `zstd` extra.
      TAR_GZ         one stream, gzip, no parallelism available at all.

    `level` defaults per format (6 for zip and gzip, 3 for zstd). Higher
    trades time for size; on zstd the jump to 19 costs far more than it
    saves and is rarely worth it.

    Everything runs in the calling thread unless `workers` asks otherwise.
    Threads are opt-in because they are not free and not always welcome: a
    pool only pays for itself once there is enough work to hide the cost of
    starting and joining it, and code inside an event loop, a request
    handler or someone else's worker should not have threads created
    underneath it uninvited.

    `workers` is what opts in, and it takes either:

      an int      a count of threads to create. -1 asks for one per core;
                  0 or None stay on the calling thread.
      an Executor a pool you already own, used instead of creating one.
                  Any concurrent.futures.Executor.

    One argument rather than the `workers` plus `executor` pair this used
    to take. They were never independent -- a count and a pool are two ways
    of answering the same question, and passing both left it ambiguous
    which one won. Anything else raises ValidationError rather than being
    quietly ignored.

    On ZIP the work goes to fastzip, which deflates members on a pool and
    appends them already compressed; zipfile itself cannot be driven that
    way at all, since it permits one open write handle and offers no way to
    hand it bytes that are compressed already. That needs the `fastzip`
    extra, and without it this warns and compresses on the calling thread
    instead -- the archive is still correct, only slower. Note fastzip
    reaches libz through ctypes and so does not import on Windows at all.

    On TAR_ZST a count goes to the codec instead, where it buys nothing at
    the default level and starts paying from about level 10 up. A pool has
    nothing to do there -- a tar is one stream -- so it is accepted and
    ignored. TAR_GZ has no parallelism to offer at all.

    Serial compression uses ZipFile.write() and nothing else, so the mtime,
    the mode, the CRC, the UTF-8 flag and the central directory are the
    standard library's business. An earlier version bypassed it to keep
    compression parallelisable and paid for that with three separate
    metadata bugs; delegating parallelism to fastzip made the bypass
    unnecessary and it is gone.

    Available as `backup_folder` too, the name this had before.
    """

    src = resolve_path(src, strict=True)
    dest = resolve_path(dest)

    if not src.is_dir():
        raise ValidationError(f"compress_folder: {str(src)!r} is not a directory")

    fmt = ArchiveFormat(format)
    dest_path = dest / f"{src.name}.{fmt.value}" if dest.is_dir() else dest

    if fmt is ArchiveFormat.TAR_ZST:
        _require_zstd()

    if dest_path.is_relative_to(src):
        # Both rules are anchored at the archive's own place in the tree, not
        # written as bare names. "backup.zip" as a name would match every
        # file called that at any depth, and the temp-file rule without its
        # directory and its ".tmp" suffix would take out anything the user
        # happens to keep beside it under a leading dot.
        here = dest_path.relative_to(src).as_posix()
        folder = here.rpartition("/")[0]
        folder = f"{folder}/" if folder else ""

        exclude = (
            f"/{here}",
            _temp_file_rule(folder, f".{dest_path.name}."),
            exclude,
        )

    if exclude_hidden:
        exclude = (_is_hidden, exclude)

    

    walk = _Compressor(
        str(src),
        _Filter.from_rules(iter_flat_cont(include), iter_flat_cont(exclude)),
        follow_symlinks=follow_symlinks,
    )

    with atomic_write(dest_path, binary=True, fsync=fsync) as out:
        walk.write(out, fmt, level, workers)

    return dest_path


#: The name this had before it described what it does rather than why you
#: would call it. Kept so existing code keeps working.
backup_folder = compress_folder


def extract_archive(
    src: PathLike,
    dest: PathLike,
    *,
    include: Optional[NestedContainer[_Rule]] = None,
    exclude: Optional[NestedContainer[_Rule]] = None,
    limits: ArchiveLimits = ArchiveLimits(),
    password: Optional[Union[str, bytes]] = None,
    workers: Optional[Union[int, Executor]] = None,
    atomic: bool = False,
    cleanup_on_error: bool = False,
    ) -> Path:

    """Extract the archive at `src` into `dest`, and return `dest`.

    The format is read from the file's own leading bytes, so any of the
    three compress_folder writes is handled without being told which -- and
    a renamed archive still extracts as what it actually is. `dest` is
    created if it does not exist.

    `include`/`exclude` are the same ladder compress_folder takes -- whole
    paths, then predicates, then bare names, then globs -- matched here
    against each member's name inside the archive, so a single file or
    subtree can be pulled out of a large one without unpacking the rest.

    They are asymmetric in the same way, and for the same reason: see
    compress_folder. `exclude` reaches into a directory, `include` does
    not, so exclude="docs" drops everything under docs/ while
    include="docs" selects nothing and include="docs/**" is what selects
    the subtree.

    Reproducing that here takes a little work, because an archive lists
    "a/b/c.txt" and never mentions "a" or "a/b": there is no walk to prune
    anything. Each of a member's directories is therefore put to the same
    test a walk would put it to before the member itself is. Without that
    an exclusion would mean one thing when writing an archive and another
    when reading it.

    A predicate is handed the ZipInfo or TarInfo rather than an
    os.DirEntry, and None for the directories the archive never listed.

    Nothing is ever written outside `dest`, and that is not a setting.
    Archive member names are attacker-controlled strings, and "../" or an
    absolute path in one is how an archive overwrites files it was never
    given access to -- the "Zip Slip" class of bug, and CVE-2007-4559 for
    tarfile, whose extractall() had no protection against this at all
    before the filters added in 3.12.

    So a member whose name is absolute, in any spelling, or that climbs out
    with "..", is refused and logged. Not stripped and kept, which is what
    tar itself does: that silently rewrites what the archive asked for, and
    an archive asking to write outside the directory it was handed has not
    earned the benefit of the doubt on its other names either.

    `limits` is everything else the extraction is allowed to do -- six
    ceilings, a directory check of your own, and four policies. See
    ArchiveLimits. Nothing is capped unless you
    ask, because there is no honest default; every policy, by contrast,
    starts at the safe answer:

        extract_archive(upload, dest, limits=ArchiveLimits(max_ratio=200,
                                                    max_total_size=1 << 30))

    max_files counts every member written -- files, directories and links
    alike -- because what it bounds is how many filesystem entries an
    archive may create, and max_dir_entries is that same count taken one
    directory at a time: the breadth of the tree, where max_depth is its
    height. The ratio is the zip bomb check and the one worth setting on
    anything you did not make yourself.

    `limits.dir_check` is the same question in your own words, and the one
    check that sees what actually arrived: a callable handed one extracted
    directory at a time, as a Path with its contents already in it, which
    returns false to drop that directory and its whole subtree, or raises
    to stop the extraction with your own exception. It is asked once per
    directory, including the ones a member's path implies but the archive
    never listed, after every member is written and before anything reaches
    `dest`:

        extract_archive(upload, dest, limits=ArchiveLimits(
            dir_check=lambda d: d.name != "node_modules"))

        extract_archive(upload, dest, limits=ArchiveLimits(
            dir_check=lambda d: not any(p.suffix == ".exe" for p in d.iterdir())))

    Setting one makes the extraction stage, whatever `atomic` says, because
    dropping a directory means removing it after it was written and doing
    that in `dest` would take anything already there with it. So `d` is a
    path under a temporary sibling of `dest`: judge it by `d.name` or by
    what is inside it, not by its prefix.

    Every ceiling is judged twice -- from the archive's own headers before
    a member's bytes are written, so a bomb is refused rather than
    survived, and again from the bytes themselves as they are written, so
    an archive whose headers do not describe it is refused too. Both count
    what is actually being written: a member the filter dropped costs
    nothing against max_total_size, because you never asked for it.

    The policies cover the member kinds that can reach outside the
    destination or overwrite what is already there -- symlinks, hardlinks,
    duplicates, and a name that already exists. Each has an enum of its own
    in pytrove.enums -- ArchiveLinkPolicy, ArchiveOverwritePolicy and
    ArchiveDuplicatePolicy -- and each is a str enum, so a member and its
    own spelling are the same value and mean the same thing:

        extract_archive(mine, dest, limits=ArchiveLimits(symlinks=ArchiveLinkPolicy.ALLOW))
        extract_archive(mine, dest, limits=ArchiveLimits(symlinks="allow"))
        extract_archive(mine, dest, limits=ArchiveLimits.permissive())

    A link is still refused if it points outside `dest` even when allowed,
    because a later member written "through" it would escape while its own
    name looked harmless.

    A spelling that is neither is not rejected, and does not have to be:
    no comparison matches it, so it falls to the conservative side of its
    own setting -- "allowed" behaves as skip, "validate_frist" as
    streaming. A typo can cost you an unwritten member; it cannot buy an
    archive a permission you did not grant.

    Two members can also collide without either name being a duplicate --
    "Readme.txt" and "README.TXT" land on one path on Windows and on macOS
    -- so the check is made against the resolved target and the second of
    them meets `overwrite` like anything else already there.

    `password` decrypts a ZIP whose members were encrypted, as `str` (taken
    as UTF-8) or as `bytes`. It covers the traditional ZipCrypto scheme,
    which is what the standard library implements and what the `-e` flag of
    the zip command produces; WinZip's AES is refused with a message saying
    so, because zipfile cannot read it at all. An encrypted member reached
    without a password is refused rather than written as ciphertext. The
    tar formats carry no encryption of their own, so a password passed with
    one is reported and not used. Note ZipCrypto is weak by modern
    standards -- it is a compatibility feature, not a way to protect
    anything.

    Members are written into `dest` itself. An archive is never given a
    folder of its own inside it -- backup.zip extracted into backup/ puts
    its members directly there, not into backup/backup/ -- and `dest` is
    created if it does not exist. What is already there stays: extracting
    into a directory adds to it, and only a member landing on an existing
    name touches anything, which is what `limits.overwrite` is for.

    Every member is written as it is read, and every check happens on the
    way past -- so a member that proves the archive wrong stops the
    extraction where it stands, with what came before it already on disk.
    Two arguments decide what to do about that, and neither is on by
    default: a half-extracted tree is sometimes the useful thing, and
    deleting it is not a decision to make for you.

    `cleanup_on_error=True` removes what this call created if it does not
    finish. Only that: every file written and every directory that was not
    already there is noted as it is created and undone in reverse, so
    nothing that was in `dest` beforehand is touched.

    `atomic=True` writes into a sibling temp directory and moves it into
    place only when everything has been written, so a failure part-way
    leaves the destination as it was rather than half-filled. The move is
    one rename when `dest` does not yet exist, which is instantaneous and
    genuinely all-or-nothing. When it does exist the members are moved into
    it one at a time, merging directory by directory, so the same files
    survive as on the ordinary path. No platform can do that in a single
    step, so the guarantee there is narrower and honest about it: nothing
    reaches `dest` until the whole archive has been read, but a failure
    during the move itself leaves some members moved and raises. A `dest`
    that exists and is not a directory is refused either way, so the
    careful branch cannot be the one that destroys a file.

    `workers` takes a count or an executor, exactly as compress_folder
    does, and only ZIP can use it: its members are compressed
    independently and zlib releases the GIL, so inflating and writing go to
    the pool while the single file handle stays on this thread. A tar is
    one stream read in order and has nothing to parallelise, so `workers`
    is ignored there entirely -- not even checked, since refusing a value
    about to be ignored would be a distinction without a difference -- and
    passing anything at all is logged as having changed nothing. It is off by
    default -- a pool measured 1.3x to 1.6x on Windows and 0.99x on Linux
    on many small files, where write syscalls dominate; it pays on large
    members, not on numerous ones.
    """

    src = resolve_path(src, strict=True)
    dest = resolve_path(dest)

    if not src.is_file():
        raise ValidationError(f"extract_archive: {str(src)!r} is not a file")

    fmt = _Extractor.detect_format(str(src))

    if fmt is ArchiveFormat.TAR_ZST:
        _require_zstd()

    _Extractor(
        src, dest,
        _Filter.from_rules(to_frozenset(iter_flat_cont(include)),
                           to_frozenset(iter_flat_cont(exclude)),
                           who="extract_archive"),
        limits,
        password.encode() if isinstance(password, str) else password,
    ).run(fmt, workers, atomic, cleanup_on_error)

    return dest


__all__ = (
    "backup_folder",
    "compress_folder",
    "extract_archive",
)
