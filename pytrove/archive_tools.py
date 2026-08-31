from pathlib import Path
from typing import Optional, Union
from concurrent.futures import Executor

from .typings import ArchiveLimits, NestedContainer, PathLike
from .enums import ArchiveFormat
from .errors import ValidationError
from .iter_tools import iter_flat_cont
from .files_tools import atomic_write, resolve_path
from ._archive_tools import (
    _Compressor,
    _Extractor,
    _Filter,
    _Rule,
    _format_from_suffix,
    _is_hidden,
    _require_zstd,
    _temp_file_rule,
)


def compress_folder(
    src: PathLike,
    dest: PathLike,
    *,
    format: Optional[Union[ArchiveFormat, str]] = None,
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

        pip install 'pytrove[archive]'

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

      ZIP            every file compressed independently, which is the only
                     format here whose work can be split across threads.
      TAR_ZST        one stream, parallelised inside zstandard instead when
                     asked; reaches gzip's ratio several times faster.
                     Needs the `zstd` extra.
      TAR_GZ         one stream, gzip, no parallelism available at all.

    It defaults to None, which means read it off `dest`: "backup.tar.gz"
    asks for TAR_GZ and does not have to say so twice. The extensions
    recognised are the three values above plus ".tgz". A `dest` naming a
    directory has no extension to read and falls back to ZIP, which is what
    this defaulted to before; a `dest` naming a file with an extension this
    does not know raises rather than guessing, since writing a zip to
    "backup.tar.gz" is the mistake reading the name is there to catch.

    Passing both is allowed and checked. They have to agree -- format=ZIP
    with dest="backup.tar.gz" raises ValidationError instead of writing an
    archive whose name lies about what is in it. An extension this does not
    recognise says nothing and so cannot disagree: format=ZIP with
    dest="backup.bin" writes a zip called backup.bin.

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

    # What the destination's own name says, and None when it says nothing
    # -- an extension this does not know, or a directory, which has no name
    # to read because the archive inside it has not been named yet.
    into_dir = dest.is_dir()
    named = None if into_dir else _format_from_suffix(dest.name)

    if format is None:
        if named is None and not into_dir:
            raise ValidationError(
                f"compress_folder: cannot tell what format {dest.name!r} should "
                f"be -- end it with one of "
                f"{', '.join('.' + f.value for f in ArchiveFormat)}, or pass format="
            )

        # A directory falls back to ZIP, which is what this defaulted to
        # before the name was consulted at all.
        fmt = named or ArchiveFormat.ZIP
    else:
        fmt = ArchiveFormat(format)

        if named is not None and named is not fmt:
            raise ValidationError(
                f"compress_folder: format={fmt.value!r} does not match "
                f"{dest.name!r}, which names a {named.value} archive -- pass one "
                f"answer or the other, not two that disagree"
            )

    dest_path = dest / f"{src.name}.{fmt.value}" if into_dir else dest

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
    cleanup_on_error: bool = True,
    ) -> Path:

    """Extract the archive at `src` into `dest`, and return `dest`.

    Members are written into the destination itself, not into a folder
    named after the archive: backup.zip extracted to backup/ puts its
    members directly in backup/.

    The format is read from the archive's own leading bytes, and only from
    its extension when those say nothing -- a .zip that is really a tar.gz
    extracts, and one renamed to hide what it is is not trusted on the
    strength of its name.

    An archive is untrusted input. Every member name is an attacker's
    string until it has been checked, and the checking is not optional:

      a name that is absolute in any spelling, climbs out with "..",
      carries a NUL or a backslash, or holds an empty segment is refused
      outright, and so is one that lands outside `dest` once the
      filesystem has resolved it -- through a "..", a drive, a symlink an
      earlier member left in the way, or a Windows junction that was
      already there.

      a link member is refused by default (`limits.symlinks` and
      `limits.hardlinks`), and where it is allowed, a destination that
      resolves outside `dest` is refused whatever the policy says. That is
      not a setting: a later member written "through" an escaping link
      lands outside while its own name still looks harmless.

      a fifo, a socket or a device node is never recreated, in either
      container.

    `include` and `exclude` are the same rules compress_folder takes, in
    the same order, matched against each member's name -- see its
    docstring for the ladder and for what the `archive` extra changes
    about globs. A directory's exclusion reaches what is under it here
    too, so exclude="docs" empties docs/ on the way out as it does on the
    way in.

    `limits` is an ArchiveLimits: the six ceilings that stop a zip bomb
    (max_files, max_total_size, max_file_size, max_ratio, max_depth,
    max_dir_entries), the four policies (symlinks, hardlinks, overwrite,
    duplicates) and dir_check. See ArchiveLimits, and note what max_ratio
    can and cannot see -- it is read from the header, which a tar does not
    carry at all.

    `password` decrypts a zip written with the legacy ZipCrypto scheme,
    which is all the standard library reads; a WinZip AES member is
    refused rather than half-read. A tar has no encryption of its own, so
    passing one there is reported and ignored.

    `workers` splits the work across threads, and only on a zip -- members
    are compressed independently there and zlib releases the GIL. It takes
    a count or an Executor, exactly as compress_folder does. A tar is one
    stream read in order, so a value passed with one is reported and
    ignored rather than silently doing nothing.

    `atomic` writes into a sibling temp directory and moves the result in
    only once the whole archive has been read, so an archive that turns
    out to be wrong part-way leaves `dest` as it was. What is atomic is
    the *decision*, not the move: an empty or missing destination is taken
    by one rename, and an existing one is merged into member by member,
    which no platform does in a single step. Nothing reaches `dest` before
    the archive has been read to the end either way, and a file the
    archive never mentioned is left where it is.

    `cleanup_on_error` is on by default and is the same promise without a
    staging directory: everything this run created is removed again if it
    does not finish, and nothing that was in `dest` beforehand is touched.
    Pass False to keep what came out before the archive turned out to be
    wrong.

    Raises ValidationError for an archive whose contents do not match its
    own metadata, ArchiveLimitError for a ceiling, ArchivePolicyError for
    a policy set to "error", and NotADirectoryError when `dest` exists and
    is not a directory. A refusal that is not any of those -- an unsafe
    name, an escaping link, a member the filter dropped -- is logged and
    skipped, so one bad member does not cost the other several thousand.
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
        _Filter.from_rules(iter_flat_cont(include), iter_flat_cont(exclude), who="extract_archive"),
        limits, 
        password.encode() if isinstance(password, str) else password, 
    ).run(fmt, workers, atomic, cleanup_on_error)

    return dest


__all__ = (
    "backup_folder",
    "compress_folder",
    "extract_archive",
)
