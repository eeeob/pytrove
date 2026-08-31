"""Walking, filtering and archive-assembly internals for archive_tools.

Kept out of archive_tools.py the same way _files_tools/_async_tools are.
What it imports from the package is the foundation and the layer just above
it -- errors, enums, typings, and the three small helpers files_tools,
iter_tools and callable_tools -- none of which imports back, so this cannot
take part in a cycle.
"""

import gzip
import logging
import ntpath
import os
import posixpath
import tarfile
import tempfile
import threading
import zipfile
import stat
import sys
import io

from collections import deque
from concurrent.futures import Executor, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import (
    NoReturn, Callable, FrozenSet,
    Literal, Optional, Tuple, Union,
    Iterator, NamedTuple, List, 
    TypeAlias, Iterable,
    TYPE_CHECKING,
)


from .errors import ValidationError, ArchiveLimitError, ArchivePolicyError
from .enums import ArchiveFormat, ArchiveLinkPolicy, ArchiveOverwritePolicy
from .typings.archive import ArchiveLimits
from .files_tools import remove_path
from .iter_tools import dedupe
from .callable_tools import safe_call

try:
    from compression import zstd as std_zstd  # type: ignore[import-not-found]
except ImportError:
    std_zstd = None
try:
    import zstandard
except ImportError:
    zstandard = None
try:
    from fastzip.write import WZip
except (TypeError, ImportError):
    WZip = None
try:
    from pathspec import PathSpec, GitIgnoreSpec
except ImportError:
    if not TYPE_CHECKING:
        PathSpec = GitIgnoreSpec = None


log = logging.getLogger(__name__)


# --- constants -------------------------------------------------------

#: How much of a member is held in memory while it is copied out. One
#: buffer per member being written, so a 4 GB file costs this and not its
#: own size.
_COPY_BUF = 1 << 20

#: The longest link destination read out of a zip member's data. A
#: destination is a path, and 4096 is the longest any platform stores one;
#: a header claiming more is describing something that is not a link.
_LINK_MAX = 4096

#: Cache miss. _Extractor._cleared stores None for "this directory may not
#: be written into", so absence cannot be spelled with None and dict.get
#: needs a default of its own.
_MISS = object()

#: Windows strips a trailing dot or space from every path component before
#: it reaches the filesystem, so "foo. " and "foo" name one file there and
#: "..." names the directory itself. _Extractor._under does that stripping
#: itself rather than handing the OS a name it will quietly rewrite.
_NT = os.name == "nt"

#: Whether one path can be spelled two ways and still be one file. True on
#: Windows, where normcase already folds it, and on macOS, where normcase
#: is the identity function and the filesystem folds anyway -- so a key
#: built for "is this the same file" has to fold there by hand. Linux is
#: neither, and folding would make two different files look like one.
_FOLD_CASE = _NT or sys.platform == "darwin"

#: Whether os.link can be told not to follow a symlink in its last
#: component. Linux can (linkat), Windows ignores the argument, and macOS
#: raises NotImplementedError for it -- which is not an OSError, so it
#: would not be caught where a link failure is caught. Asked once here
#: rather than guessed at the call site.
_LINK_NOFOLLOW = os.link in os.supports_follow_symlinks

#: Extension -> format. The one table both directions read: compress_folder
#: to learn what `dest` is asking to be written, extract_archive to fall
#: back on when an archive's leading bytes say nothing. None of the four is
#: a suffix of another, so the order is only the order they were written.
_SUFFIXES = (
    (".zip", ArchiveFormat.ZIP),
    (".tar.zst", ArchiveFormat.TAR_ZST),
    (".tar.gz", ArchiveFormat.TAR_GZ),
    (".tgz", ArchiveFormat.TAR_GZ),
)


# --- type aliases ----------------------------------------------------

#: (absolute path, posix arcname, is_dir) -- what the compression walk
#: yields, once per entry it keeps.
_WalkEntry: TypeAlias = Tuple[str, str, bool]

#: What a predicate rule is handed alongside the path: an os.DirEntry while
#: a tree is walked, the container's own header while an archive is read,
#: and None for a directory an archive only implied.
_RawEntry: TypeAlias = Optional[Union["os.DirEntry", zipfile.ZipInfo, tarfile.TarInfo]]

#: One filter rule as a caller writes it -- a name, a path, a glob, or a
#: predicate taking the two above.
_Rule: TypeAlias = Union[str, Callable[[str, _RawEntry], bool]]


# --- helpers ---------------------------------------------------------

def _format_from_suffix(name: str) -> Optional[ArchiveFormat]:
    """Which format a name claims to be, or None if it claims nothing."""

    lower = name.lower()

    for suffix, fmt in _SUFFIXES:
        if lower.endswith(suffix):
            return fmt

    return None


def _is_plain_dir(path) -> bool:
    """Whether this is a real directory and not any kind of link to one.

    Path.is_symlink() is not enough on Windows, where a junction is a
    directory reparse point: is_dir() answers True and is_symlink() answers
    False, so a guard written as `is_dir() and not is_symlink()` walks
    straight into one. st_reparse_tag is what names it, and it is only
    present on Windows -- getattr gives 0 everywhere else, where S_ISLNK
    has already answered.

    lstat rather than stat, so nothing is followed to be asked about.
    """

    try:
        st = os.lstat(path)
    except OSError:
        return False

    return (stat.S_ISDIR(st.st_mode)
            and not stat.S_ISLNK(st.st_mode)
            and not getattr(st, "st_reparse_tag", 0))


def _split_workers(workers, who: str) -> Tuple[Optional[int], Optional[Executor]]:
    """Read the one `workers` argument as a count and a pool.

    One argument does two jobs because it is one decision: how much
    parallelism, and where it comes from. A pool is recognised as itself,
    an int as a count to build one from, -1 as one per core, and None or 0
    as staying on the calling thread.

    bool is refused along with everything else that is neither. It is an
    int in Python, so workers=True would otherwise pass silently as one
    worker, which is not what anybody typing it meant.
    """

    if workers is None or isinstance(workers, Executor):
        return None, workers

    if isinstance(workers, int) and not isinstance(workers, bool):
        return ((os.cpu_count() or 1) if workers < 0 else workers), None

    raise ValidationError(
        f"{who}: workers takes a count or an executor, "
        f"not {type(workers).__name__}"
    )


def _is_hidden(_, entry: Optional[os.DirEntry]) -> bool:
    """Whether the walk should treat this entry as hidden.

    compress_folder's `exclude_hidden` is this and nothing else -- an
    ordinary exclude predicate, so it prunes a hidden directory the way any
    other rule does and loses to the include rungs above it.

    Both conventions, because one tree can carry either: a leading dot, and
    the Windows hidden attribute. `entry` is None where a rule is asked
    about something that is not a filesystem entry -- a directory an
    archive only implied -- and nothing can be read off it, so it is not
    hidden.
    """

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

    def rule(rel: str, _) -> bool:
        if not rel.startswith(folder):
            return False

        base = rel[cut:]

        return ("/" not in base
                and base.startswith(prefix)
                and base.endswith(".tmp"))

    return rule


def _require_zstd() -> None:
    """Raise the standard missing-extra error unless zstd is available.

    Called from both directions -- compress_folder writes tar.zst and
    extract_archive reads it -- so the message names neither.

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
            "tar.zst needs zstd support, and this "
            "interpreter was built without it -- compression.zstd is part "
            "of the standard library from 3.14, but only when Python was "
            "compiled against libzstd. Either use an interpreter that was, "
            "or install the third-party backend: pip install zstandard"
        )

    raise ImportError(
        "To use this feature, all required packages must be installed.\n"
        "Run: pip install 'pytrove[archive]'\n"
        "\n"
        "Required : 'zstandard'\n"
        "Missing  : 'zstandard'"
    )



class _Rules(NamedTuple):
    """One side's rules, sorted onto the rungs they are tested on.

    Splitting up front is what keeps the per-entry cost flat. Names and
    whole paths -- "node_modules", ".git", "src/main.py", the majority of
    what anyone passes -- carry no metacharacter and mean exactly what
    they say, so they live in sets and cost one hash lookup however many
    of them there are. Only real globs reach fnmatch, which is a regex
    translation and a cache lookup per pattern per entry.
    """

    paths: FrozenSet[str] = frozenset()
    funcs: Tuple[Callable[[str, _RawEntry], bool], ...] = ()
    names: FrozenSet[str] = frozenset()
    globs: Tuple[str, ...] = ()
    spec: Optional["PathSpec[GitIgnoreSpec]"] = None

    def __bool__(self):
        return any(self)

@dataclass(slots=True)
class _Filter:
    include_rules: _Rules
    exclude_rules: _Rules
    who: str = "compress_folder"

    @staticmethod
    @lru_cache(maxsize=256, typed=True)
    def sort(items: Iterable[_Rule]) -> _Rules:
        """Sort one side's rules onto their rungs, keyed on the set itself.

        Cached across calls, not within one: this runs twice per
        compress_folder or extract_archive -- once per side, from
        from_rules -- and never again while the walk is running. Measured
        on a 60-entry tree: two calls. What the cache saves is the second
        run with the same rules, which is what a loop over many folders
        does.

        Keyed on the tuple itself, so a tuple of names or globs hashes by
        content and matches. A predicate does not: two lambdas that read
        the same are different objects, and a closure built per call --
        compress_folder's own temp-file rule is one -- misses every time
        and leaves an entry behind. The cache holds a strong reference to
        what it was keyed on, so those entries keep their closures alive
        until 256 of them push the oldest out. Bounded, but not free, and
        the reason not to grow maxsize.

        A bare name is the only thing that reaches the name rung. Anything
        carrying a path of its own -- "src/main.py", "/logs" -- names one
        place rather than a name, which is a more specific thing to say
        and ranks accordingly. Separators are normalised and a leading
        "./" or a trailing "/" dropped -- for globs as well as for the
        rest, since the walk produces one spelling and a rule has to be in
        it whatever shape the caller wrote.
        """

        paths, funcs, names, globs = set(), [], set(), []

        for item in items:
            if isinstance(item, str):
                item = Path(item)
            if isinstance(item, Path):
                item = "" if (pos := item.as_posix()) in (".", "/") else pos
            
            if callable(item):
                funcs.append(item)
            elif not isinstance(item, str) or not item:
                raise ValidationError(f"{item!r} is not a pattern or a callable")
            elif any(c in item for c in ("*", "?", "[")):
                globs.append(item)
            elif "/" in item:
                paths.add(item.lstrip("/"))
            else:
                names.add(item)
                
        
        spec = (
            None if PathSpec is None or not globs
            else PathSpec.from_lines("gitignore", (("\\" + g if g[:1] in ("#", "!") else g) for g in globs))
        )

        if spec is not None:
            globs.clear()

        return _Rules(
            frozenset(paths), 
            tuple(funcs), 
            frozenset(names),
            tuple(globs), 
            spec
        )

    @classmethod
    def from_rules(cls, include: Iterable[_Rule], exclude: Iterable[_Rule], who: str = "compress_folder") -> "_Filter":
        """Build a filter from the two sides, naming `who` in any complaint.

        sort() is shared by both public functions and cached on the rules
        alone, so it cannot know which one was called and must not guess --
        a message naming compress_folder is wrong every time the caller was
        extract_archive. The name is put on here instead, where nothing is
        cached and the caller is known.
        """

        try:
            return cls(
                cls.sort(tuple(dedupe(include))),
                cls.sort(tuple(dedupe(exclude))),
                who,
            )
        except ValidationError as exc:
            raise ValidationError(f"{who}: {exc}") from None

    @staticmethod
    def glob_hit(rel: str, rules: _Rules) -> bool:
        """Whether one side's globs match, by whichever backend holds them."""

        if rules.spec is not None:
            return rules.spec.match_file(rel)

        for pat in rules.globs:
            if fnmatchcase(rel, pat):
                return True

        return False

    def __bool__(self) -> bool:
        return bool(self.include_rules or self.exclude_rules)

    @staticmethod
    def _ask(fn: Callable, rel: str, raw: _RawEntry, side: str) -> bool:
        """Put one entry to one of the caller's predicates.

        Wrapped because the two halves of the library hand a predicate
        different second arguments -- an os.DirEntry on a walk, a ZipInfo
        or TarInfo on an extraction, None for a directory an archive only
        implied -- and a rule written for one of them raises on the other.
        The documented example, `lambda p, e: e.stat().st_size < 4096`,
        does exactly that: DirEntry has stat(), ZipInfo does not.

        Left to itself that surfaces as a bare AttributeError from inside
        a walk, and on the extraction side it aborts the run -- which,
        with cleanup_on_error on, takes back everything already written.
        The error is still an error and is still raised; what this adds is
        which rule, which side, and which entry.
        """

        try:
            return bool(fn(rel, raw))
        except Exception as exc:
            raise ValidationError(
                f"{side}: the rule {getattr(fn, '__name__', fn)!r} raised "
                f"{type(exc).__name__} on {rel!r} -- note the second argument "
                f"is an os.DirEntry while a folder is walked and the archive's "
                f"own header (ZipInfo/TarInfo, or None for an implied "
                f"directory) while one is read, so a rule that reads it has to "
                f"handle both"
            ) from exc

    def matches(self, rel: str, raw: _RawEntry = None) -> bool:
        """Whether the entry at `rel` belongs in the archive.

        The ladder, walked from the top: the first rung that matches is the
        whole answer and nothing below it is consulted. That order is the
        precedence rule and the cost model at once -- a hash lookup, then
        the caller's own callables, then another hash lookup, then pattern
        matching -- so the common answers are also the early ones.

        `raw` is whatever the caller is looking at: an os.DirEntry on a
        walk, a ZipInfo or TarInfo on an extraction, None for a directory
        an archive only implied. Only the predicate rung uses it, and it is
        passed straight through, so a rule can ask about the thing itself
        -- its size, its mtime, whether it is a directory -- rather than
        only about its name.

        A rule is matched against this entry and nothing else. What a
        directory matched says nothing about what is under it, so "sub/*"
        means the direct children of sub and not the subtree -- "sub/**"
        is how the subtree is spelled. The one exception is an exclusion,
        which reaches downward by pruning rather than by matching; that is
        enter()'s business, not this function's.
        """

        if not self:
            return True

        inc, exc = self.include_rules, self.exclude_rules

        if rel in inc.paths:
            return True
        if rel in exc.paths:
            return False

        for fn in inc.funcs:
            if self._ask(fn, rel, raw, self.who):
                return True
        for fn in exc.funcs:
            if self._ask(fn, rel, raw, self.who):
                return False

        base = rel.rsplit("/", 1)[-1]

        if base in inc.names:
            return True
        if base in exc.names:
            return False

        if self.glob_hit(rel, exc):
            return False
        if self.glob_hit(rel, inc):
            return True

        return not bool(inc)

    def enter(self, rel: str, raw: _RawEntry = None) -> bool:
        """Whether the walk should open the directory at `rel`.

        Not the same question as matches(). A directory is not an archive
        member in its own right -- it is recorded only once a file inside
        it is kept -- so the include side has no say here: a match may lie
        any depth below, and "docs/*" says nothing about "docs" itself
        while meaning everything under it. Only exclude answers, and only
        to prune.

        Pruning is also what carries an exclusion down: the subtree under a
        directory that loses here is never looked at, so exclude="logs"
        empties logs/ without any rule having to match the files inside.

        The early return costs one _Rules.__bool__ and saves the rsplit,
        which is the most expensive thing in the function.
        """

        exc = self.exclude_rules

        if not exc:
            return True

        if rel in exc.paths:
            return False

        for fn in exc.funcs:
            if self._ask(fn, rel, raw, self.who):
                return False

        if rel.rsplit("/", 1)[-1] in exc.names:
            return False

        return not self.glob_hit(rel, exc)

@dataclass(slots=True)
class _Compressor:
    """Turns a folder into an archive: the walk, then one of the writers.

    Holds what every entry is judged against -- the root and the filter --
    so the walk is an iterator over the object rather than a function with
    arguments threaded through it. Iterating is what does the work; write()
    is handed the open destination.

    There is nothing here about hidden files, nor about the archive keeping
    itself out of its own contents. Both used to be conditions in the loop
    and are now ordinary exclude rules that compress_folder builds -- see
    _is_hidden and _archive_itself there. The walk asks the filter and
    nothing else, so there is one place where an entry can be left out and
    one order in which the reasons are tried.
    """

    root: str
    flt: "_Filter"
    follow_symlinks: bool = False

    def write(self, out, fmt, level=None, workers=None) -> None:
        """Walk the tree into `out` in whichever container `fmt` names.

        `workers` is one argument doing two jobs, because it is one
        decision: how much parallelism, and where it comes from. A pool is
        recognised as itself, an int as a count to build one from, -1 as
        one per core, and None or 0 as staying on the calling thread. The
        two used to be separate arguments, which made three of the four
        combinations meaningless and one of them ambiguous.

        Only the zip writer can use a pool. The tar formats compress one
        stream, so a count goes to the codec and a pool has nothing to do
        there -- see _write_tar.
        """

        count, pool = _split_workers(workers, "compress_folder")

        if fmt is ArchiveFormat.ZIP:
            # `level or 6`, which this used to say, turned level=0 into 6 --
            # and 0 is a real setting there: store the bytes, compress
            # nothing. Only None means "whatever the format's default is".
            self._write_zip(out, 6 if level is None else level, count, pool)
        else:
            self._write_tar(out, fmt, level, count, pool)

    def __iter__(self) -> Iterator[_WalkEntry]:
        """Yield (absolute path, relative posix arcname, is_dir) for the archive.

        Uses an explicit stack over os.scandir() rather than os.walk() or
        Path.rglob(): scandir hands back the file type from the directory entry
        the OS already read, so a deep tree costs one syscall per directory
        instead of an extra stat() per child. Measured ~10x on a 3k-file tree.

        `flt` decides what is kept, and it is asked two different questions.
        A file gets matches(): does this belong in the archive. A directory
        gets enter(): is it worth opening. They are different questions
        because a directory is not an archive member in its own right, and
        keeping them apart is what lets "docs/*" work -- it says nothing about
        "docs" itself while meaning everything under it, so asking matches()
        about the directory would prune the very tree it selects.

        Only exclude answers enter(), and that is where a directory's verdict
        reaches its contents: the subtree under a directory that loses is
        never looked at, so exclude="logs" empties logs/ without any rule
        having to match the files inside. It is also the whole of the
        optimisation -- an excluded subtree costs one check rather than a walk
        of everything in it. The cost of putting it here is that an exclusion
        cannot be undone from deeper in: include="build/report.json" does not
        survive exclude="build", the same limitation gitignore documents, for
        the same reason.

        The include side has no equivalent and travels nowhere: every file is
        matched on its own path. "sub/*" therefore means the direct children
        of sub, not the subtree -- "sub/**" is how the subtree is spelled.

        Directories are emitted only once a file inside them is kept, never on
        their own: an empty directory contributes nothing to a backup, and a
        directory whose only contents were excluded is empty as far as the
        archive is concerned. Ancestors are emitted before the file that
        needed them, so an extractor always creates a parent before its child.

        """

        # Bound once: the loop below reads every one of these per entry, and
        # a local is a slot lookup where an attribute is a dict lookup.
        root, flt, follow_symlinks = self.root, self.flt, self.follow_symlinks

        stack = [root]
        emitted = set()

        while stack:
            current = stack.pop()

            try:
                with os.scandir(current) as it:
                    entries = list(it)
            except OSError as exc:
                # A directory that vanished or was never readable is skipped
                # rather than aborting an otherwise complete backup -- but
                # everything under it is now missing, so say so.
                log.warning("compress_folder: cannot read directory %r (%s)", current, exc)
                continue

            for entry in entries:
                rel = os.path.relpath(entry.path, root).replace(os.sep, "/")

                try:
                    is_dir = entry.is_dir(follow_symlinks=follow_symlinks)
                    is_file = entry.is_file(follow_symlinks=follow_symlinks)
                except OSError as exc:
                    # scandir usually hands the type back for free, so this
                    # is the uncommon case: the platform gave no d_type, or
                    # follow_symlinks asked for the target, and the stat that
                    # answers it failed. FileNotFoundError is not among the
                    # reasons -- DirEntry catches that one itself and reports
                    # False -- so what is left is a directory that is not
                    # searchable, a symlink chain too deep to follow, a share
                    # that went away, an I/O error on the medium.
                    #
                    # Skipping is right: something whose type cannot be read
                    # cannot be archived. Saying nothing was not. This was
                    # the one place a file could disappear out of a backup
                    # without a word, while both neighbouring failures logged.
                    log.warning(
                        "compress_folder: cannot read the type of %r, "
                        "leaving it out (%s)", entry.path, exc,
                    )
                    continue

                if not is_dir and not is_file:
                    continue

                if is_dir:
                    if flt.enter(rel, entry):
                        stack.append(entry.path)

                elif flt.matches(rel, entry):
                    yield from self._ancestors(rel, emitted)
                    yield entry.path, rel, False

    def _ancestors(self, rel: str, emitted: set) -> Iterator[_WalkEntry]:
        """Yield the directories `rel` needs, in order, each of them once.

        An extractor has to create a parent before the child that lives in
        it, so the ancestors are emitted just ahead of the file that needed
        them. They are emitted here, on the way past, rather than when the
        directory itself was walked, because a directory is only worth
        recording once something inside it has actually survived the
        filter -- an empty one, or one whose whole contents were excluded,
        contributes nothing to a backup.

        `emitted` is the walk's own set rather than state on the object, so
        iterating twice starts clean. It is keyed on the full branch and
        not on a basename, which is what keeps "logs/logs/logs" three
        distinct levels instead of one.
        """

        parts = rel.split("/")[:-1]

        for i in range(1, len(parts) + 1):
            branch = "/".join(parts[:i])

            if branch not in emitted:
                emitted.add(branch)
                yield os.path.join(self.root, *parts[:i]), branch, True

    def _write_zip(self, out, level, workers, executor) -> None:
        """Write every walked entry into a zip container.

        Two writers, and which one is decided here rather than by the
        caller: fastzip when a pool was asked for and it is installed,
        zipfile otherwise. They differ in what reaches the archive -- see
        the directory record below -- so the choice is worth reading.
        """

        entries = iter(self)
        use_fastzip = False

        if (workers or 0) > 1 or executor is not None:
            if WZip is None:
                log.warning(
                    "compress_folder: workers requested but fastzip is not available, "
                    "compressing on this thread instead. Install it with: "
                    "pip install 'pytrove[archive]'"
                )
            else:
                use_fastzip = True

        if use_fastzip:
            zf = WZip(
                Path(getattr(out, "name", "archive.zip")), fobj=out, 
                threads=workers or None, executor=executor, 
                force_zip64=True,
            )
        else:
            zf = zipfile.ZipFile(
                out, "w", zipfile.ZIP_DEFLATED, 
                allowZip64=True, compresslevel=level, strict_timestamps=False
            )

        with zf:
            for path, arcname, is_dir in entries:
                # fastzip writes members, not entries: it has no directory
                # record to add. Nothing is lost by leaving them out -- the
                # extractor creates a member's parents anyway -- but an archive
                # written with workers does list one fewer name.
                if is_dir and use_fastzip:
                    continue

                try:
                    if use_fastzip:
                        zf.write(Path(path), archive_path=Path(arcname))
                    else:
                        # ZipInfo.from_file appends the "/" that marks a
                        # directory, so the arcname is passed as it is.
                        zf.write(path, arcname)
                except OSError as exc:
                    log.warning("compress_folder: skipped %r (%s)", path, exc)

    def _write_tar(self, out, fmt, level, workers=None, executor=None) -> None:
        """Write every walked entry into a tar container, compressed.

        A pool cannot be used here and is not quietly dropped. A tar is one
        stream: members are written into it in order, so there is nothing to
        hand to a second thread. What parallelism tar.zst has lives inside
        the codec and is asked for with a count, not with an executor.
        """

        entries = iter(self)

        if executor is not None:
            log.warning(
                "compress_folder: %s writes one stream and cannot use the "
                "executor passed as workers, so it was ignored and this ran "
                "on the calling thread. Pass a count instead to parallelise "
                "the codec on tar.zst, or use format='zip' to use the pool.",
                fmt.value,
            )

        if fmt is ArchiveFormat.TAR_ZST:
            if level is None:
                level = 3
            if not workers or workers <= 1:
                workers = 0

            if std_zstd is None:
                compressor = zstandard.ZstdCompressor(level=level, threads=workers).stream_writer(out, closefd=False)
            else:
                compressor = std_zstd.ZstdFile(
                    out, "wb",
                    options={
                        std_zstd.CompressionParameter.compression_level: level, 
                        std_zstd.CompressionParameter.nb_workers: workers
                    },
                )
        else:
            compressor = gzip.GzipFile(
                fileobj=out,
                mode="wb",
                compresslevel=6 if level is None else level,
            )

        # dereference=True, and it is not a detail. Without it tarfile
        # calls os.lstat, which does two things this library does not want:
        # it stores a symlink as a link member, and it turns the second
        # name of a hardlinked file into a LNKTYPE member pointing at the
        # first. Both come back out of extract_archive as link members,
        # which it refuses by default -- so an ordinary tree with one
        # hardlink in it produced a tar.gz that this library would not
        # extract. Measured, and zip never had the problem: ZipInfo.from_file
        # stats through the link, so the two containers said different
        # things about one tree.
        #
        # Following costs size where a tree has many links to one file --
        # each is stored whole -- which is the same bargain zip makes, and
        # the same one _Compressor.__iter__ already made by yielding a
        # symlink's target as content under follow_symlinks.
        with compressor as stream, tarfile.open(fileobj=stream, mode="w|", dereference=True) as tf:
            for path, arcname, _ in entries:
                # recursive=False because the walk already yields every member,
                # with the include/exclude rules applied.
                try:
                    tf.add(path, arcname=arcname, recursive=False)
                except OSError as exc:
                    # Same policy as the zip path: a file that vanished mid-run
                    # is dropped rather than failing the whole backup.
                    log.warning("compress_folder: skipped %r (%s)", path, exc)
                    continue



class _Member(NamedTuple):
    """One archive entry, in the single shape the pipeline understands.

    zipfile and tarfile describe a member so differently that every check
    downstream would otherwise be written twice. Reading both into this
    first is what leaves one admit-and-write loop instead of two.

    `raw` is the ZipInfo or TarInfo it came from, and is what a predicate
    rule is handed, so a rule can still ask whatever the container records
    beyond the fields named here -- its mtime, its CRC, its mode.

    `packed` is 0 where the container has no per-member compressed size,
    which is every tar: a tar member is stored uncompressed inside one
    stream, so there is no ratio to take against it.

    `target` is the link destination the archive recorded, and None for
    everything that is not a link. It is also None for a zip's link
    members as they come out of the manifest, because a zip keeps a
    destination in the member's *content* rather than in its header -- see
    _zip, which reads it and fills the field in before writing.
    """

    name: str
    raw: Union[zipfile.ZipInfo, tarfile.TarInfo]
    size: int #الحجم قبل الضغط
    packed: int #الحجم مضغوط
    kind: Literal["dir", "file", "symlink", "hardlink", "other"]
    target: Optional[str] = None

@dataclass(slots=True)
class _Limiter:
    """Every question ArchiveLimits has a say in, answered in one place.

    The ceilings used to live here and the four policies in the extractor,
    each sitting next to whichever line happened to trip it. That meant
    "what can `limits` actually do?" was answered across two classes and
    five methods, and adding a setting meant finding all of them. They are
    together now: the extractor asks and never reads a policy itself, so
    this class is the whole of what a caller can configure.

    The ceilings are judged from the archive's own headers, in count(),
    before any of a member's bytes reach the disk -- so a bomb is stopped
    at the member that proves it rather than after the filesystem is full.

    Sizes are then re-weighed as they are written, in grew(), from what the
    member really produced rather than what it claimed. Only sizes: see
    grew() for why a ratio cannot be asked a second time, and count() for
    what trusting the header costs on max_ratio.

    What is counted is what is actually being written, not what the archive
    holds: a member the filter dropped costs nothing against max_total_size,
    because the caller never asked for it.

    One instance per extraction. Nothing here is ever cleared, because
    nothing needs to be: the archive is read once and the tallies only ever
    grow.
    """

    limits: ArchiveLimits
    src: Path

    files: int = field(init=False, default=0)        #: members admitted so far
    total: int = field(init=False, default=0)        #: bytes they will expand to

    #: The five tallies, each keyed on what its own setting is about. All of
    #: them start empty and none is ever cleared: one instance answers for
    #: one pass over one archive, and a second pass builds a second.
    _breadth: dict = field(init=False, default_factory=dict)   #: directory -> entries in it
    _counted: set = field(init=False, default_factory=set)     #: every path counted, once
    _seen: set = field(init=False, default_factory=set)        #: member names, `duplicates`
    _taken: set = field(init=False, default_factory=set)       #: resolved paths, `overwrite`


    # --- the ceilings ----------------------------------------------------

    def count(self, m: _Member) -> None:
        """Weigh one member against all six ceilings, or raise.

        A directory or a link counts as an entry but not as bytes: what
        max_files bounds is how many filesystem entries an archive may
        create, and what max_total_size bounds is how much disk it may take.

        max_ratio is judged here and nowhere else, and it is judged from
        the header, because the number it needs exists nowhere else. A tar
        records no per-member compressed size -- the whole stream is one
        unit -- so m.packed is 0 there and the check is skipped entirely: a
        tar.gz expanding 1027x was measured passing max_ratio=1.0001
        without a word. On a zip m.packed is the central directory's word,
        and a member declaring a compressed size larger than it has reads
        as a flatter ratio than it is. That lie costs the forger, since the
        bytes must be present in the file or the read fails, but it is a
        lie the check cannot see.

        Both are the price of a per-member ratio, and the price is paid
        here rather than papered over: reading back what a member really
        occupied is not something either container will tell you. Where
        that matters, max_total_size and max_file_size bound the same
        attack in absolute bytes, and both are re-weighed against what is
        actually written -- see grew().

        The sizes below are the archive's claim too, but a claim that
        cannot be usefully understated: both containers stop a member's
        reader at its declared length, so a member that claims less than it
        holds hands out less, not more.

        max_dir_entries is the one that is not a comparison against a
        number the member carries, so it is spelled out below rather than
        hidden behind a call: it has to register the member in its parent,
        and every directory above it in that one's parent, before it has
        anything to compare. Walking the whole path is what makes the count
        match the filesystem. An archive listing "a/b/c.txt" and nothing
        else still creates "a" and "a/b", and those are entries in their
        parents whether or not the archive troubled to mention them -- so
        each ancestor is registered once, on the way past, exactly as the
        compression walk emits them.

        `_counted` is what keeps "once" true: members of one directory
        arrive together, so the ancestors of the second are the ancestors
        of the first and cost a set lookup rather than a recount.
        """

        lim = self.limits
        name = m.name
        size = m.size if m.kind == "file" else 0

        if lim.max_depth is not None and (depth := name.count("/")) > lim.max_depth:
            self._fail(f"member {name!r} is nested {depth} deep, "
                       f"over the {lim.max_depth} allowed")

        if lim.max_dir_entries is not None:
            parts = name.split("/")

            for i in range(1, len(parts) + 1):
                path = "/".join(parts[:i])

                if path in self._counted:
                    continue

                self._counted.add(path)
                parent = path.rpartition("/")[0]
                self._breadth[parent] = held = self._breadth.get(parent, 0) + 1

                if held > lim.max_dir_entries:
                    self._fail(
                        f"directory {parent or '.'!r} holds more than the "
                        f"{lim.max_dir_entries} entries allowed"
                    )

        if lim.max_file_size is not None and size > lim.max_file_size:
            self._fail(f"member {name!r} is {size} bytes, over the "
                       f"{lim.max_file_size} allowed")

        if lim.max_ratio is not None and m.packed > 0:
            ratio = size / m.packed

            if ratio > lim.max_ratio:
                self._fail(f"member {name!r} expands {ratio:.0f}x "
                           f"({m.packed} -> {size} bytes), over the "
                           f"{lim.max_ratio:g}x allowed")

        self.files += 1
        self.total += size

        if lim.max_files is not None and self.files > lim.max_files:
            self._fail(f"archive holds more than the {lim.max_files} members allowed")

        if lim.max_total_size is not None and self.total > lim.max_total_size:
            self._fail(f"archive expands past the {lim.max_total_size} bytes allowed")

    def grew(self, name: str, member_total: int) -> None:
        lim = self.limits

        if lim.max_file_size is not None and member_total > lim.max_file_size:
            self._fail(f"member {name!r} has written {member_total} bytes, over the {lim.max_file_size} allowed")

    # --- the four policies -----------------------------------------------

    def allows_name(self, name: str) -> bool:
        """Whether this member name has not been used already -- `duplicates`.

        A zip can hold one name twice; nothing in the format forbids it,
        and it is how an archive smuggles a second version of a file past a
        reader that only looks at the first. The first one wins either way.
        """

        if name in self._seen:
            return self._deny(self.limits.duplicates, f"duplicate member {name!r}")

        self._seen.add(name)

        return True

    def allows_target(self, name: str, target: Path) -> bool:
        """Whether this member may take that path -- `overwrite`.

        Keyed on the resolved target rather than on the member name, which
        covers two cases with one lookup. Two members whose names differ
        can still land on one path -- "Readme.txt" and "README.TXT" on a
        case-insensitive filesystem -- and the second would otherwise
        overwrite the first whatever the policy said, since neither is a
        duplicate name and the first was not yet on disk when the second
        was judged.

        `target` is where the member finally comes to rest, which under
        `atomic` is not where it is about to be written -- _Extractor._place
        works it out before calling. Asking about the staging directory
        instead would make this setting mean nothing there, since nothing is
        ever already in a directory made moments ago.

        Nothing is remembered under OVERWRITE: collisions are allowed
        there, so a set of every path written would be paid for and never
        read.
        """

        if self.limits.overwrite == ArchiveOverwritePolicy.OVERWRITE:
            return True

        if target.exists() or (key := os.path.normcase(str(target))) in self._taken:
            return self._deny(self.limits.overwrite, f"member {name!r} already exists")

        self._taken.add(key)

        return True

    def allows_link(self, m: _Member) -> bool:
        """Whether a link member may be recreated -- `symlinks`/`hardlinks`.

        Only the policy. Whether the link stays inside the destination is
        not a setting and is not asked here: see _Extractor._link, which
        refuses an escaping link whatever this answers.
        """

        policy = self.limits.symlinks if m.kind == "symlink" else self.limits.hardlinks

        if policy == ArchiveLinkPolicy.ALLOW:
            return True

        return self._deny(policy, f"{m.kind} member {m.name!r}")

    def allows_dir(self, path: Path) -> bool:
        """Put one extracted directory to `dir_check`.

        Handed the directory itself, on disk, with its contents already in
        it -- so the callable can look inside rather than only at the name.
        That is the whole reason it runs where it does; see
        _Extractor._inspect for what that costs.

        Three ways for the callable to answer, and it picks: None or
        anything true lets the directory stand, anything false takes it and
        everything under it back out again, and raising stops the
        extraction with the caller's own exception -- which run() lets
        straight out, after clearing the staging directory.

        None counts as yes so that a check written only to raise -- the
        shape most of them take -- does not have to end in `return True`.

        No memo any more. The walk reaches each directory exactly once, so
        there is nothing to remember: the archive-name pass this replaced
        had to be told, because members of one directory arrive over and
        over and each of them named the same ancestors.
        """

        check = self.limits.dir_check

        if check is None:
            return True

        verdict = check(path)

        if verdict is None or verdict:
            return True

        log.warning("extract_archive: dropped directory %r from %s, "
                    "refused by dir_check", str(path), self.src.name)

        return False

    # --- how a refusal is reported ---------------------------------------

    def _deny(self, policy: str, why: str) -> bool:
        """Act on a policy that is not the permissive one, and refuse.

        Always returns False, so every caller can say `return self._deny(..)`
        -- each of them is turning a member away, and the only question the
        policy answers is whether to take the rest of the archive with it.

        Compared as a string on purpose: four different enums reach this,
        and "error" is the one value they all spell the same way.
        """

        if policy == "error":
            raise ArchivePolicyError(f"extract_archive: {self.src.name}: {why}")

        log.info("extract_archive: skipped %s in %s", why, self.src.name)

        return False

    def _fail(self, why: str) -> NoReturn:
        raise ArchiveLimitError(f"extract_archive: {self.src.name}: {why}")

@dataclass(slots=True)
class _ZipReaders:
    """One open ZipFile per thread, because a file handle is not shareable.

    Zip only, and named so: it is the pool's half of _zip and nothing in
    _tar has a use for it -- a tar is one stream read in order, with one
    handle and one thread.

    zipfile seeks a single handle to reach a member, so two threads reading
    through one ZipFile read each other's bytes. Giving each worker its own
    handle is what makes the pool worth having at all, and it means nothing
    on the read path needs a lock.

    Every handle opened is kept, because a thread-local is invisible from
    the thread that has to close them.
    """

    src: Path
    pwd: Optional[bytes]

    #: The three below are built here rather than passed in: a handle store
    #: is only ever its own, and sharing one between two extractions would
    #: hand a worker a file the other one is closing.
    _local: threading.local = field(init=False, default_factory=threading.local)
    _all: List[zipfile.ZipFile] = field(init=False, default_factory=list)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)

    def get(self) -> zipfile.ZipFile:
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
        with self._lock:
            handles, self._all = self._all, []

        for zf in handles:
            try:
                zf.close()
            except OSError:
                pass

@dataclass(slots=True)
class _Extractor:
    """Turns an archive back into files, and refuses what it should not.

    An archive is untrusted input: member names are attacker-controlled
    strings, not paths anything has checked. "../../etc/cron.d/x" or
    "C:/Windows/System32/x" extracts outside the destination entirely --
    the "Zip Slip" class of bug, and CVE-2007-4559 for tarfile, whose
    extractall() offered no protection at all before the filters added in
    3.12. That is why the checking lives here rather than being delegated.

    There is one pipeline, not one per format. zipfile and tarfile are read
    into _Member, and from there every member passes the same gate --
    _place -- so a rule proved on a zip holds on a tar.

    That gate used to be two, _admit and _place, split along a real line:
    _admit was answered from the archive's own headers and touched no
    filesystem, so on a zip -- where infolist() knows every header before a
    byte is written -- the whole of it could be settled in a first loop and
    the survivors written in a second. That is what the split bought, and
    it is gone: the zip path streams now, exactly as the tar path always
    had to, so both halves are answered one member at a time in the same
    place. Two functions called only ever as `_admit(m) and _place(m)`, one
    repeating the other's name check, were a seam with nothing on the far
    side of it.

    What the split described is still true and is now the shape of the
    function instead: the header half runs first and completely, and only
    then does anything ask the filesystem. That order matters -- a member
    the filter dropped must not be counted against the ceilings, and the
    path must be resolved as late as possible, because an earlier member
    can be a symlink and change where a later name lands. Deciding every
    path first and writing afterwards is exactly the window a Zip Slip
    through a planted link needs.

    The gate decides nothing `limits` covers. It asks _Limiter, which owns
    every ceiling and every policy along with the state they need -- so
    what a caller can configure is described in one class, and this one is
    left with the two questions that are its own: what a name may mean, and
    where it lands.

    The state is per-extraction rather than per-member, and most of it is
    the same shape: an answer keyed on a member's directory part. Members
    of one directory arrive together in every archive, so the answer wanted
    is almost always the one just stored.
    """

    src: Path
    dest: Path
    flt: "_Filter"
    limits: "ArchiveLimits" = ArchiveLimits()
    password: Optional[bytes] = None
    _root: Path = field(init=False, default=None)                              # type: ignore[assignment]
    _limiter: "_Limiter" = field(init=False, default=None)                     # type: ignore[assignment]
    _cleared: dict = field(init=False, default_factory=dict)
    _ancestry: dict = field(init=False, default_factory=dict)
    _made: set = field(init=False, default_factory=set)
    _built: Optional[list] = field(init=False, default=None)    

    # --- entry points ----------------------------------------------------

    def run(self, fmt: ArchiveFormat, workers=None, atomic: bool = False, cleanup_on_error: bool = False) -> None:
        """Extract, optionally through a staging directory. Once.

        One archive per object, by construction rather than by a guard.
        The object holds a destination it has already resolved paths
        against, a directory cache, and a _Limiter that has already spent
        its ceilings; a second run() would answer the second archive with
        the first one's state. Nothing here checks for that, because
        nothing here can reach it -- extract_archive builds one per call
        and this class is cheap to build.

        `atomic` writes into a sibling temp directory -- a sibling because
        the last step is a rename and a rename does not cross a filesystem
        -- and moves it into place only once everything has been written,
        so a breach part-way through leaves the destination as it was
        rather than half-filled.

        The move is one rename when the destination does not yet exist,
        which is genuinely instantaneous. When it does exist the rename is
        still tried -- POSIX takes it if the destination is empty, Windows
        refuses it always -- and a refusal is what asks for the merge,
        which moves the members in one at a time and is not atomic. Nothing
        is deleted to make the rename possible: clearing the destination
        first and failing the rename after is how a caller ends up with
        neither, and it is the one ordering this must not use.

        A failure at that last step leaves the staged tree on disk, beside
        the destination and named in the log, rather than removing what has
        not been moved yet.

        `cleanup_on_error` is the same promise made without a staging
        directory: whatever this run created is removed again if it does
        not finish. extract_archive leaves it off and turns `atomic` on
        instead, which answers the same question earlier -- nothing reaches
        the destination at all until the archive has been read to the end.
        It is what a caller reaches for after turning `atomic` off, when
        writing straight into the destination is wanted but a half-written
        tree is not.

        What it undoes is only what this run made. Every file written and
        every directory that was not already there goes into a ledger as it
        is created, outermost first, and the ledger is walked in that same
        order: remove_path takes a directory whole, so the first entry of a
        subtree removes the rest of it and everything after it is already
        gone. dedupe because one path can be entered twice, under
        `overwrite`. A directory in the ledger is one that did not exist
        when this started, so nothing that was in `dest` beforehand is ever
        touched. It does nothing under `atomic`, or with a dir_check set,
        since both stage already and the staging directory is discarded
        whole.

        Neither branch creates the path above the destination. `dest`
        itself is made, and under `atomic` the staging directory is made
        beside it -- both of which need `dest.parent` to exist already, or
        this raises FileNotFoundError before an archive is read.

        A destination that exists and is not a directory is refused here,
        before either branch runs. The streaming branch would have been
        stopped by its own first mkdir anyway; the staging branch never
        touches the destination until the rename, so without this it would
        replace that file with a directory -- destroying it, and only on
        the branch asked for because it is the careful one.
        """

        if self.dest.exists() and not self.dest.is_dir():
            raise NotADirectoryError(f"extract_archive: {str(self.dest)!r} exists and is not a directory")


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
        except:
            if staged is not None:
                remove_path(staged)
            elif self._built:
                for path in dedupe(self._built):
                    safe_call(remove_path, path, include_exc=OSError, log_exc=True)
            raise

        if staged is None:
            return

        # Nothing is cleared away to make room for something that may not
        # arrive. Removing the destination first so that os.replace could
        # rename onto it is how a caller ends up with neither: measured,
        # `dest` gone and the members left under a hidden temp name when
        # the replace that followed failed.
        #
        # So the rename is tried, and a refusal is what asks for the merge.
        # A destination that is not there is renamed onto in one step,
        # which is genuinely all-or-nothing. One that is there is renamed
        # onto where the platform allows it -- POSIX does when it is empty,
        # Windows never -- and merged member by member when it does not,
        # which is not atomic and cannot be: no platform moves a tree into
        # an existing one in a single step.
        #
        # A failure at this last step leaves the staged tree on disk rather
        # than removing what has not been moved, and says where it is.
        try:
            try:
                os.replace(staged, self.dest)
            except OSError:
                if not self.dest.exists():
                    raise

                self._graft(staged, self.dest)
                remove_path(staged)
        except BaseException:
            log.error("extract_archive: could not put %s at %r -- what came out "
                      "of it is in %r", self.src.name, str(self.dest), str(staged))
            raise

    def _inspect(self, root: Path) -> None:
        """Put every extracted directory to `dir_check`, outermost first.

        Runs once the members are all written and before anything is
        committed, because the question it asks cannot be answered any
        earlier: a check that wants to know what is in a directory needs
        the directory to have its contents. The name-only version this
        replaced ran during the walk, which was cheaper -- a refused
        subtree was never written at all -- and could only ever be told the
        name.

        The price is paid in that order. A refused directory has already
        been extracted, counted against the ceilings, and is now removed;
        with a large subtree that is real work done and undone. What it is
        not is destructive: run() stages whenever a dir_check is set, so
        the tree being pruned holds this archive and nothing else, and the
        destination is only written once the pruning is over.

        Outermost first, and a refusal is not descended into, so a branch
        cut near the root still costs one call however deep it went -- the
        same shape the walk had. Directories only: a symlink to one is not
        followed, which would otherwise walk the check out of the tree.
        """

        if self.limits.dir_check is None:
            return

        # A deque, because this walks outermost-first and popping the
        # front of a list moves every other element each time -- O(n) per
        # directory on a tree that can hold thousands.
        stack = deque([root])

        while stack:
            here = stack.popleft()

            try:
                with os.scandir(here) as it:
                    entries = list(it)
            except OSError as exc:
                # `here`, not `root`: the failure is one directory's, and
                # naming the root said nothing about which.
                log.warning("extract_archive: cannot read back %r (%s)", str(here), exc)
                continue

            for entry in entries:
                if not entry.is_dir(follow_symlinks=False):
                    continue

                path = Path(entry.path)

                if self._limiter.allows_dir(path):
                    stack.append(path)
                else:
                    remove_path(path)

    def _graft(self, staged: Path, dest: Path) -> None:
        """Move everything in `staged` into `dest`, directory by directory.

        A directory that exists on both sides is descended into rather than
        replaced, which is the whole of what "merge" means here: it is what
        keeps a file the archive never mentioned. Anything else is moved
        over what is there, which is what a non-staged run does when it
        writes onto an existing name -- and `overwrite` has already had its
        say about this exact path, because _place asks about where the
        member lands rather than about the staging directory.

        A destination entry that is a directory is never taken by
        anything that is not one. That is _link's rule, and this is where
        it has to be repeated: under `atomic` _link is writing into an
        empty staging tree and never sees the directory it would refuse,
        so without this a link -- or an ordinary file -- named after a
        directory of the caller's removed it here instead.

        A destination entry that is a link is never descended into, even
        when it points at a directory. Following one would move members
        outside the destination, which is the single thing this class
        exists to prevent; it is replaced like any other member instead.

        "A link" means _is_plain_dir, not is_symlink(). A Windows junction
        is a directory reparse point that reports is_dir() and does not
        report is_symlink(), so the obvious spelling of this check walked
        into one -- and only here, because the non-staged path resolves
        through it in _under and refuses the member before it is written.
        Staging is what postponed the question to a place that was asking
        it the wrong way.
        """

        # An explicit stack, not recursion. One frame per level meant a
        # crafted archive could exhaust the interpreter's: measured, 1500
        # nested directories raised RecursionError out of the middle of the
        # merge, leaving the destination half-written and the caller an
        # error that said nothing about archives. Nothing bounds an
        # archive's nesting unless the caller sets max_depth.
        pairs = [(staged, dest)]

        while pairs:
            here, there = pairs.pop()

            # The handle is closed before anything is moved: an open
            # directory handle is what makes a Windows rmtree fail, and the
            # caller removes `staged` the moment this returns. Materialised
            # for the same reason -- scandir does not promise what it sees
            # while the directory is being emptied underneath it, and every
            # branch below empties it.
            with os.scandir(here) as it:
                entries = list(it)

            for entry in entries:
                target = there / entry.name

                # _is_plain_dir on the destination side, not
                # `is_dir() and not is_symlink()`. A Windows junction
                # passes that pair -- is_dir() True, is_symlink() False --
                # so a destination holding one was descended into and every
                # member under it was moved wherever it pointed. Measured:
                # a junction planted in `dest` before the run took
                # "sub/PWNED.txt" outside it, and only on the staged path,
                # because a non-staged run resolves through the junction in
                # _under and refuses the member there instead.
                #
                # Anything that is not a plain directory is replaced rather
                # than entered, which is what the archive asked for anyway.
                if entry.is_dir(follow_symlinks=False) and _is_plain_dir(target):
                    pairs.append((Path(entry.path), target))
                    continue

                # The rule _link states, applied to the other half of the
                # road: nothing that is not a directory takes a path a
                # directory holds. _link refuses it where it writes, and
                # under `atomic` it never sees it -- the staging directory
                # is empty, so nothing is standing in the way there and the
                # member is made. This is the first place the two sides
                # meet, and it used to answer by removing the directory:
                # measured, an archive with a link member named after a
                # directory of the caller's took the whole tree away,
                # silently, on the default path.
                #
                # A directory over a directory is the branch above and is a
                # merge. Everything else here is one entry replacing one
                # entry, which is what `overwrite` is about -- and a
                # directory is not one entry.
                if _is_plain_dir(target):
                    log.warning("extract_archive: refused %r from %s, a directory "
                                "stands at %r", entry.name, self.src.name, str(target))
                    continue

                # One entry, removed as one, and never remove_path: it
                # sends a directory to rmtree, and rmtree cannot remove a
                # Windows junction -- not a directory it can walk, not a
                # file it can unlink -- so with ignore_errors it left the
                # junction standing and said nothing, and os.replace then
                # failed with a bare Access denied. unlink takes a file or
                # a symlink; rmdir takes a directory reparse point, and
                # takes the link rather than what it points at. A plain
                # directory never reaches here -- it was either descended
                # into or refused above -- so nothing recursive is wanted.
                if target.is_symlink() or target.exists():
                    try:
                        os.unlink(target)
                    except OSError:
                        os.rmdir(target)

                os.replace(entry.path, target)


    @staticmethod
    def detect_format(path: str) -> ArchiveFormat:
        """Identify an archive by its leading bytes, falling back to its suffix.

        Content beats extension because the extension is a claim, not a fact --
        a .zip that is really a tar.gz should extract, and one renamed to hide
        what it is should not be trusted on the strength of its name.
        """

        try:
            with open(path, "rb") as f:
                head = f.read(4)
        except OSError:
            head = b""

        if head:
            for magic, fmt in ((b"PK\x03\x04", ArchiveFormat.ZIP),
                            (b"PK\x05\x06", ArchiveFormat.ZIP),   # an empty archive
                            (b"\x1f\x8b", ArchiveFormat.TAR_GZ),
                            (b"\x28\xb5\x2f\xfd", ArchiveFormat.TAR_ZST)):
                if head.startswith(magic):
                    return fmt

        if (fmt := _format_from_suffix(path)) is not None:
            return fmt

        raise ValidationError(f"extract_archive: cannot tell what format {path!r} is")

    # --- where a member may go -------------------------------------------


    def _member_kept(self, m: _Member) -> bool:
        """Apply the walk's two questions to one archive member.

        An archive lists "a/b/c.txt" and never mentions "a" or "a/b", so
        there is no walk here to prune anything and nothing that would
        carry a directory's verdict down on its own. Replaying it is what
        keeps the two halves of the library saying the same thing: without
        it, exclude="docs" would empty docs/ when compressing and do
        nothing at all when extracting.

        The replay is the loop below: enter() is asked about every directory
        the name passes through, and the first refusal stops it, so a
        subtree cut off near the root costs one check however deep the name
        went.

        `_ancestry` memoises one thing and one thing only -- what enter()
        said about that one directory -- and every level of the walk is
        written into it, not just the branch that was asked for. Keying it
        on the whole branch instead meant "t0/a0/b0/c" and "t0/a0/b0" and
        "t0/a0" were three unrelated entries, each re-walking from the root
        to build itself: measured on a 444-directory archive, 1452 enter()
        calls for 444 distinct directories, with the top level asked 37
        times over.

        The fast path is still one lookup. A value is only ever written for
        a directory the walk actually reached, and reaching it means every
        ancestor answered True -- so finding `head` already in there is
        proof of the whole branch, not just of its last step.
        """

        head = m.name.rpartition("/")[0]

        if head:
            if (ok := self._ancestry.get(head)) is None:
                parts = head.split("/")

                for i in range(1, len(parts) + 1):
                    branch = "/".join(parts[:i])

                    if (ok := self._ancestry.get(branch)) is None:
                        self._ancestry[branch] = ok = self.flt.enter(branch)

                    if not ok:
                        break

            if not ok:
                return False

        return self.flt.matches(m.name, m.raw)

    def _under(self, name: str) -> Optional[Path]:
        """Where a posix name under the root lands, or None if it may not.

        The filesystem half of _place, in a method because _link needs the
        same answer about where a link points. Everything a member path is
        put through, a link destination is put through: the directory
        cache, the trailing dot or space that only a full resolve notices,
        the fold of "..", the follow of links already on disk, the guard
        against a name the platform will not parse, and the demand that
        what comes out lands inside the root.

        What comes back is the path that will really be written, not the
        one the archive spelled. On Windows every component loses its
        trailing dots and spaces on the way into the filesystem -- measured:
        mkdir("dots...") makes "dots", mkdir("d. ") makes "d", and "...",
        ".. ." and ". ." each resolve to the directory itself. Stripping
        that here rather than leaving it to the OS is what makes one path
        one answer: "clash.txt" and "clash.txt. " are one file, so they
        have to be one target, or `overwrite` compares two keys for one
        file and the pool hands two workers one path believing they differ.
        A component that strips away to nothing means "here" and is
        dropped, which is what "." has always meant; a name that is nothing
        but such components addresses the root itself and is refused, since
        there is no member to write there. POSIX stores those names as they
        are, so nothing is stripped there.

        Most names then go through the directory cache. A basename carries
        no separator -- the name check refuses one that does -- so it cannot
        climb out of a directory already cleared: resolving the directory
        once and joining the name onto it gives the same answer for a
        fraction of the resolve() calls, which on Windows walk up until
        something exists and measured a third of the whole extraction.

        The cache is filled with setdefault and read with get, because this
        runs on the pool as well as on the main thread -- _zip hands a link
        member to a worker like any other, and _link asks this where the
        link points. `if parent not in cache: cache[parent] = ...` is a
        check and then an act with a resolve() in between, which is long
        enough for another thread to run the whole of it; setdefault is one
        dict operation and cannot be interleaved. Two threads may then
        resolve the same directory at once, which costs a syscall and
        settles on one answer rather than on whichever wrote last. _MISS
        rather than None as the default, since None is what this stores for
        a directory that may not be written into at all.
        """

        if _NT:
            name = "/".join(part for raw in name.split("/") if (part := raw.rstrip(". ")))

            if not name:
                return 

        parent, _, base = name.rpartition("/")

        if (safe := self._cleared.get(parent, _MISS)) is _MISS:
            safe = self._cleared.setdefault(
                parent,
                (
                    (
                        _target
                        if (
                            (_target := safe_call((self._root / parent).resolve, strict=False, include_exc=(ValueError, OSError), log_exc=True)) is not None
                            and _target.is_relative_to(self._root)
                        )
                        else None
                    )
                    if parent
                    else self._root
                )
            )

        return None if safe is None else safe / base

    # --- whether it may be written ---------------------------------------

    def _place(self, m: _Member) -> Optional[Path]:
        """Where this member goes, or None if it is not to be written.

        Called one member ahead of its own write, and the whole of what
        stands between an archive's word and a path on disk. Two halves,
        in this order and not the other.

        The first is answered from the archive's own account of the member
        and touches no filesystem: the name, the duplicates, the filter,
        the kind. The kind is asked here rather than in the two read
        loops, so a fifo, a socket or a device node is refused by the same
        line whichever container carried it -- both spell one in st_mode
        and both are read into _Member the same way. It is ordered
        cheapest-first and refusal-first at once, the name before the
        filter and the filter before anything else.

        The ceilings are weighed between the halves rather than at the end
        of the first, because what they bound is what is about to be
        written: a member the filter dropped and a member that resolves
        outside the destination are both refused before count() sees them,
        so neither spends an entry of max_files or bytes of
        max_total_size.

        The second asks the filesystem, and has to run here rather than
        earlier because its answer keeps changing: a symlink member
        extracted a moment ago changes where every name below it resolves
        to, and a path settled before that member existed was settled
        against a tree that is no longer the one being written to.

        Most names go through the directory cache. A basename carries no
        separator -- the name check refuses one that does -- so it cannot
        climb out of a directory already cleared: resolving the directory
        once and joining the name onto it gives the same answer for a
        fraction of the resolve() calls, which on Windows walk up until
        something exists and measured a third of the whole extraction. A
        trailing dot or space is the exception, because Windows strips one
        rather than storing it, so such a name has no faithful target and
        only the full resolve notices; POSIX takes it literally.

        Whether the path may then be taken is the limiter's -- see
        _Limiter.allows_target, which is where `overwrite` lives. It is
        asked about where the member finally comes to rest rather than
        where it is about to be written, which are the same path unless a
        staging directory is in play: nothing can already exist in a
        directory made seconds ago, so asking about that one would make
        the setting mean nothing under `atomic`.
        """

        name = m.name

        # --- what the archive says --------------------------------------

        if (
            m.kind == "other" or 
            not self._is_safe_member_name(name) or 
            (self.flt and not self._member_kept(m)) or 
            not self._limiter.allows_name(name) 
        ):
            return 

        # --- and what the filesystem says -------------------------------

        target = self._under(name)

        if target is None:
            log.warning("extract_archive: refused member %r in %s, it resolves outside the destination", name, self.src.name)
            return

        # Counted here, after the last thing that can turn the member away
        # for good. Earlier it was counted before this, so a member refused
        # for resolving outside the destination still spent an entry of
        # max_files and its bytes of max_total_size -- a ceiling reached by
        # members that were never going to be written. What is counted is
        # what is about to be, which is what the ceilings are described as
        # bounding. `overwrite` below is the one refusal that comes after,
        # and deliberately: it is a policy about a path that was otherwise
        # fine, not a judgement that the member was never real.
        self._limiter.count(m)

        if m.kind == "dir":
            return target

        return (
            target 
            if self._limiter.allows_target(name, target if self._root == self.dest else self.dest / target.relative_to(self._root)) 
            else None
        )

    # --- writing it ------------------------------------------------------

    def _mkdir(self, path: Path) -> bool:
        """Make one directory, remembering it, and say whether it is there.

        A failure is reported and skipped rather than raised, the same way
        the walk treats a directory it cannot read. The usual cause is an
        archive holding both "sub" as a file and "sub/" as a directory, and
        one contradictory member is not a reason to abandon the other
        several thousand.
        """

        if path in self._made:
            return True

        # Which levels are missing, walked up before anything is made,
        # because afterwards they all exist and nothing says which of them
        # this run created. The ledger wants that; so does the loop below.
        #
        # It also replaces mkdir(parents=True), which recurses once per
        # missing level inside pathlib: measured, an archive nesting 1500
        # directories raised RecursionError out of the standard library,
        # from a path the caller never chose. Walking up is a loop, and
        # making them bottom-up is a loop, so the depth an archive can ask
        # for is bounded by the filesystem rather than by the interpreter.
        # Once per directory, not per member -- `_made` above is what makes
        # that true -- and it stops at the first level already there, so an
        # ordinary archive pays one or two stats per new directory.
        fresh = []
        probe = path

        while probe != self._root and probe != probe.parent and not probe.exists():
            fresh.append(probe)
            probe = probe.parent

        try:
            for level in reversed(fresh):
                level.mkdir(exist_ok=True)

            if not fresh:
                # Already there, or it is the root. Asked anyway, so that a
                # file sitting at the path still reports itself below.
                path.mkdir(exist_ok=True)
        except FileExistsError:
            # With exist_ok=True this is the one thing left that raises it:
            # something is there and it is not a directory. The archive is
            # contradicting itself -- "sub" and "sub/" both -- and saying so
            # beats telling the member that needed the directory there is
            # one and failing further along with a worse message.
            log.warning("extract_archive: cannot create directory %r in %s, "
                        "a file is already there", str(path), self.src.name)
            return False
        except OSError as exc:
            log.warning("extract_archive: cannot create directory %r in %s (%s)", str(path), self.src.name, exc)
            return False

        self._made.add(path)

        if fresh and self._built is not None:
            # `fresh` was collected child-first on the way up, so it goes
            # in outermost-first -- the order the undo relies on.
            self._built.extend(reversed(fresh))

        return True

    def _link(self, m: _Member, target: Path) -> None:
        """Recreate a link member, if the policy allows and it stays inside.

        Two separate questions, and only one of them is the caller's. The
        policy is -- `symlinks` and `hardlinks`, asked of the limiter, which
        logs or raises on its own. `overwrite` is the caller's too, and was
        answered in _place like any other member; what is left here is
        carrying that answer out, since a link cannot be written over the
        way a file can -- so it is created beside its path and renamed onto
        it, which takes the path from whatever is there without a moment in
        which the path holds nothing.

        A directory is the exception, and the only thing here that refuses
        a member the policy allowed. os.replace cannot take a path from a
        directory, so the only way to obey would be to delete it and
        everything under it, and no setting in this library means that:
        `overwrite` replaces a file, which is one thing, where a directory
        is however much someone put in it.

        Whether this run made that directory is not asked, though it could
        be. An archive that lists "sub/inner.txt" and then "sub" as a link
        is describing its own tree and deleting it would take back only
        what the same archive had just written -- so that case was allowed
        once, on a set of the directories this run created. It is not any
        more, for what it cost around it: the set had to be right on every
        path into _mkdir, mkdir(parents=True) does not say which levels it
        made so the answer had to be built by hand, and the removal ran on
        a pool worker where rmtree cannot delete a file another thread
        holds open and, called with ignore_errors, said nothing when it
        gave up -- measured, half a directory removed and no link created.
        The rule is one sentence now and holds without any of that.

        What it costs is that such an archive comes out with the directory
        still a directory and the link left out, with a line in the log
        saying so. More than was asked for, never less: this refuses, it
        does not destroy.

        Containment is not. A symlink is resolved relative to its own
        directory and a hardlink relative to the archive root, and either
        way a link landing outside the destination is refused whatever the
        policy allows -- a later member written "through" it would escape
        even though its own name looked harmless, which is the whole reason
        link members are dangerous.
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

        # A directory standing in the way is refused, and that is the whole
        # of the rule: a link member never removes a directory. Not one the
        # caller had, and not one this run made either -- see the docstring
        # for why the second half is not the exception it looks like.
        #
        # is_symlink() before is_dir(): is_dir() follows a link, so a link
        # already at the target would answer yes and be refused, when it is
        # exactly what os.replace below takes the path from. On Windows a
        # junction reports is_dir() without reporting is_symlink(), so it
        # lands here and is refused rather than followed into whatever it
        # points at.
        if not target.is_symlink() and target.is_dir():
            log.warning("extract_archive: refused %s %r in %s, a directory stands at %r", m.kind, m.name, self.src.name, str(target))
            return

        # A hardlink to a link is refused rather than followed. _under
        # resolves the destination's parent and joins the last component
        # onto it without resolving that one, so a link sitting there is
        # inside the root as a name while pointing wherever it likes -- and
        # os.link follows it by default, which would give an inode outside
        # the destination a name inside it. The archive cannot plant such a
        # link itself, since every one it creates is checked; a destination
        # that already had one can.
        #
        # os.link(follow_symlinks=False) says the same thing to the kernel
        # and closes the gap between this check and the call, but only
        # where the platform has it: Windows ignores the argument and macOS
        # raises NotImplementedError for it, which is not an OSError and
        # would not be caught below. So it is asked for only where it
        # works, and the check above is what holds everywhere.
        if m.kind == "hardlink" and resolved.is_symlink():
            log.warning("extract_archive: refused hardlink %r in %s, its destination "
                        "%r is itself a link", m.name, self.src.name, str(resolved))
            return

        # Built beside the target and renamed onto it, never written over
        # it. os.replace takes the path from a file or a link in one step,
        # which is what lets a link member land where something already is
        # -- and it is the only ordering under which a link that cannot be
        # created leaves what was there alone. Creating first and clearing
        # afterwards would delete on behalf of a link that never appeared:
        # a symlink on Windows without the privilege, a hardlink across a
        # volume, a destination that has gone.
        tmp = target.with_name(f".{target.name}.{os.urandom(4).hex()}.tmp")

        try:
            if m.kind == "symlink":
                os.symlink(raw, tmp)
            elif _LINK_NOFOLLOW:
                os.link(resolved, tmp, follow_symlinks=False)
            else:
                os.link(resolved, tmp)
        except OSError as exc:
            log.warning("extract_archive: could not create %s %r (%s)", m.kind, m.name, exc)
            return

        try:
            os.replace(tmp, target)
        except OSError as exc:
            safe_call(remove_path, tmp, include_exc=OSError, log_exc=True)
            log.warning("extract_archive: could not put %s %r at %r (%s)",
                        m.kind, m.name, str(target), exc)
            return

        if self._built is not None:
            self._built.append(target)

    def _spill(self, m: _Member, data: io.BufferedIOBase, target: Path) -> None:
        """Copy one member's bytes into place, in bounded chunks.

        Streaming rather than reading the member whole: a 4 GB member costs
        one buffer here instead of its own size. The parent directory is
        the caller's business -- it has to be made on the main thread even
        when the copy runs on a pool, so that two workers never race to
        create the same one.

        The loop is written out rather than handed to shutil.copyfileobj,
        which is the same loop, because two things are checked on the way
        past. The ceilings are weighed per chunk -- see _Limiter.grew -- so
        a member that outgrows what its header claimed is stopped at the
        chunk that proves it. And the total is compared with the size the
        archive declared once the member is done.

        That last one is not a ceiling and has no setting, and it is said
        rather than enforced. A member's header says how many bytes it
        holds, and every reader in both containers stops at exactly that
        number, so a member that produces a different one is an archive
        whose metadata does not describe its own contents -- truncated, or
        edited after it was written. What is on disk is still what the
        member really carried, and it is bounded: the ceilings were weighed
        against those bytes on the way past, not against the header. So the
        mismatch is logged against the member that shows it and the rest of
        the archive is written, rather than several thousand good members
        being thrown away over one bad header.

        An OSError is different and is the environment refusing this one
        member -- a read-only path, a name the filesystem will not take, a
        full disk -- and is logged and skipped, as the walk does on the
        writing side. Nothing else is caught: a bad checksum, a limit and a
        size that does not match are all the archive being wrong, which
        every caller wants to hear.
        """

        try:
            with open(target, "wb") as out:
                if self._built is not None:
                    self._built.append(target)

                grown = 0

                while chunk := data.read(_COPY_BUF):
                    out.write(chunk)
                    grown += len(chunk)
                    self._limiter.grew(m.name, grown)
        except EOFError:
            # Both containers raise this bare, with no message at all, when
            # a member's data runs out before its header said it would --
            # zipfile reading past the end of the file, tarfile past the
            # end of the stream. `packed` is not named because a tar has
            # none; the declared size is the number that was broken.
            raise ValidationError(
                f"extract_archive: {self.src.name}: member {m.name!r} ends "
                f"before the {m.size} bytes it declares -- the archive is "
                f"truncated, or its metadata was edited"
            ) from None
        except OSError as exc:
            log.warning("extract_archive: could not write %r from %s (%s)", m.name, self.src.name, exc)
            return

        if grown != m.size:
            log.warning("extract_archive: %s: member %r declares %d bytes but "
                        "produced %d -- the archive's metadata does not describe "
                        "its contents", self.src.name, m.name, m.size, grown)

    # --- the two containers ----------------------------------------------

    def _zip_copy(self, readers: "_ZipReaders", m: _Member, target: Path) -> None:
        """Write one member into place, on whichever thread runs this.

        Zip only, and the reason the prefix is there: this is what a worker
        runs, so it must touch nothing the main thread owns -- it asks
        _ZipReaders for the handle belonging to its own thread and nothing
        else. The tar path writes through _spill directly, on the calling
        thread, with no handle of its own to fetch.

        A link comes through here as well, because on a zip a link is a
        read: the destination lives in the member's data rather than in its
        header, so it is not in the manifest and _Member.target arrived as
        None. Everything a file is put through first applies to it
        unchanged -- the encryption flag, the AES refusal, the handle -- so
        it is the same open() rather than a second one written beside it.

        That puts _link on a worker, and the state it reaches is written
        for it. _under fills the directory cache with setdefault, which is
        one dict operation where `if not in: ...` was a check and an act
        with a resolve() between them. The ledger is a list and append is
        atomic; nothing reads it until the run is over. The limiter is only
        asked about the policy, which reads a setting and returns. And two
        members landing on one path are already serialised by `inflight`,
        so the link and the file that collide with each other do not run at
        once. What stays on the main thread is what decides: _place, and
        every mkdir.

        Everything refused here is a zip's to refuse: encryption is
        recorded in a flag bit no tar has, and WinZip AES is a compression
        method number rather than a format of its own.

        ZipFile.open() is what reads the member, rather than the raw bytes
        plus a zlib call this used to do by hand. Lifting the blob out
        directly meant deflate was the only method that came back as
        itself: a stored-with-bzip2, lzma or zstd member was written to
        disk still compressed, under the right name, with nothing said. It
        also walked straight past the encryption flag, so an encrypted
        member's ciphertext was written as though it were the file, and it
        held every member whole in memory twice over.

        Going through zipfile costs a CRC check per member, which is not a
        cost: it is the only thing that notices a corrupt member at all.
        """

        info = m.raw

        if info.compress_type == 99:
            raise ValidationError(
                f"extract_archive: {self.src.name}: member {m.name!r} uses "
                f"WinZip AES encryption, which the standard library cannot read"
            )

        if info.flag_bits & 0x1 and self.password is None:
            raise ValidationError(
                f"extract_archive: {self.src.name}: member {m.name!r} is "
                f"encrypted -- pass password=... to extract it"
            )

        try:
            data = readers.get().open(info)
        except (RuntimeError, NotImplementedError) as exc:
            # A wrong password, or a compression method this build of
            # Python has no decompressor for.
            raise ValidationError(f"extract_archive: {self.src.name}: member {m.name!r}: {exc}") from None

        with data:
            if m.kind == "file":
                self._spill(m, data, target)
                return

            # Bounded rather than trusted: a destination is a path, and a
            # header claiming more than _LINK_MAX is describing something
            # that is not a symlink.
            try:
                raw = data.read(_LINK_MAX + 1)
            except OSError as exc:
                log.warning("extract_archive: could not read the destination of "
                            "%s %r in %s (%s)", m.kind, m.name, self.src.name, exc)
                return

        if len(raw) > _LINK_MAX:
            log.warning("extract_archive: refused %s %r in %s, its destination is "
                        "longer than %d bytes", m.kind, m.name, self.src.name, _LINK_MAX)
            return

        self._link(m._replace(target=os.fsdecode(raw)), target)

    def _zip(self, workers=None) -> None:
        """Read the manifest and write every member that passes.

        One pass, the same shape as _tar. A member is built from its
        central-directory entry, put to _place, then written -- and _place
        has to run there rather than earlier whatever else changes, because
        an earlier member may be a symlink and a path resolved before it
        existed answers from a tree that is no longer the one being written
        to.

        This used to be two loops: every member was checked against the
        headers first, then the survivors were written. Nothing on a zip
        needs the data for that half -- infolist() reads the central
        directory, so the name, the filter, the duplicates and the header
        ceilings are all knowable up front -- and settling them first meant
        a ceiling tripped by the five hundredth member left the first four
        hundred and ninety-nine unwritten. It also held a _Member for every
        entry in the archive at once.

        Streaming gives that up in one direction and back in the other: the
        refusal now lands with earlier members already on disk, exactly as
        it does on a tar, and `atomic` or `cleanup_on_error` is what takes
        them away again. Both formats now behave the same way, which is
        worth more than the head start. It also buys the one thing on a zip
        that is genuinely not in the manifest -- a symlink's destination,
        which lives in the member's data -- and that is read below, at the
        member, where a header-first pass could not have reached it.

        `workers` is worth having on a zip and on nothing else: members are
        compressed independently and zlib releases the GIL while inflating.
        Each worker gets its own handle -- see _ZipReaders -- because seeking
        one handle from two threads reads the wrong bytes. The main thread
        keeps the manifest handle, decides every path and creates every
        directory; a worker writes its own member and, for a link, reads
        the destination and creates it -- see _zip_copy for what that
        shares and how.
        """

        count, pool = _split_workers(workers, "extract_archive")
        own = ThreadPoolExecutor(count) if count and count > 1 else None
        pool = pool or own
        readers = _ZipReaders(self.src, self.password)
        inflight = {}          #: path -> the write filling it
        pending = deque()      #: (path, write) in the order they went out

        # How far the reader may run ahead of the writers. Without a bound
        # the manifest is submitted whole before anything is waited on:
        # measured, 3995 of 4000 members sitting in the queue at once, each
        # holding its _Member and its ZipInfo, and `inflight` holding a
        # Future per path on top. Four deep per worker keeps every one of
        # them fed while the archive is read once, not held.
        ahead = 4 * (count or 8)

        try:
            for info in readers.get().infolist():
                m = _Member(
                    info.filename.replace("\\", "/").rstrip("/"), 
                    info, 
                    info.file_size, 
                    info.compress_size, 
                    (
                        "dir" if info.is_dir()
                        else "file" if not (kind := stat.S_IFMT(info.external_attr >> 16))
                        else "symlink" if kind == stat.S_IFLNK
                        else "file" if kind == stat.S_IFREG
                        else "other"
                    ) 
                )

                target = self._place(m)

                if target is None:
                    continue

                if m.kind == "dir":
                    self._mkdir(target)
                elif not self._mkdir(target.parent):
                    continue
                elif pool is None:
                    self._zip_copy(readers, m, target)
                else:
                    # A link goes to the pool like any other member, and
                    # nothing has to be drained before it. It used to be:
                    # _link cleared a directory away to take its path, and
                    # rmtree on a worker cannot remove a file another thread
                    # holds open. A link never removes a directory now, so
                    # the only path it takes is one os.replace can take, and
                    # two members landing on one path are already serialised
                    # below.
                    # Folded where one path can be spelled two ways and
                    # still be one file. normcase does that on Windows and
                    # nothing at all on POSIX, which is right for Linux and
                    # wrong for macOS, where the filesystem folds and two
                    # workers would otherwise be handed "Readme.txt" and
                    # "README.TXT" believing they differ. Over-folding is
                    # safe here in a way it is not in _taken: this only
                    # decides what waits for what, never where a member
                    # lands, so the cost of folding two real paths together
                    # is that one waits for the other.
                    key = os.path.normcase(str(target))

                    if _FOLD_CASE:
                        key = key.lower()

                    if (earlier := inflight.pop(key, None)) is not None:
                        earlier.result()

                    inflight[key] = job = pool.submit(self._zip_copy, readers, m, target)
                    pending.append((key, job))

                    # Backpressure. The oldest write is waited on and
                    # forgotten, which bounds both the pool's queue and
                    # `inflight` -- an entry is only wanted while a later
                    # member might land on the same path, and one that has
                    # finished has nothing left to be waited for.
                    while len(pending) > ahead:
                        done_key, done_job = pending.popleft()
                        done_job.result()

                        if inflight.get(done_key) is done_job:
                            del inflight[done_key]

            for _, job in pending:
                job.result()
        finally:
            try:
                for _, job in pending:
                    job.cancel()

                wait([job for _, job in pending])
            finally:
                try:
                    if own is not None:
                        own.shutdown(wait=False, cancel_futures=True)
                finally:
                    readers.close()

    def _tar(self, fmt: ArchiveFormat, workers=None) -> None:
        """Read the tar stream and write every member that passes.

        A tar is one stream that can only be read in order, so there is
        nothing here to parallelise and `workers` is not looked at -- not
        its type either, since refusing a value that is about to be ignored
        would be a distinction without a difference. Passing anything at
        all is reported, so the caller learns it bought nothing rather than
        wondering why the archive took the same time as before.

        One pass. A member is written as it is read, and every check --
        the name, the filter, the policies, the ceilings on both the
        headers and the bytes -- happens on the way past. A member that
        proves the archive wrong stops the extraction where it stands; see
        extract_archive's `atomic` and `cleanup_on_error` for what is left
        behind when it does.
        """

        if workers is not None:
            log.warning(
                "extract_archive: %s is one stream read in order, so workers "
                "was ignored -- it changed nothing and this ran on the calling "
                "thread. Only ZIP can use it.", fmt.value,
            )

        if self.password is not None:
            log.warning(
                "extract_archive: %s has no encryption of its own, so the "
                "password given was not needed and was not used.", fmt.value,
            )

        raw = open(self.src, "rb") if fmt is ArchiveFormat.TAR_ZST else None

        if raw is None:
            stream = gzip.open(self.src, "rb")
        elif std_zstd is not None:
            stream = std_zstd.ZstdFile(raw, "rb")
        else:
            stream = zstandard.ZstdDecompressor().stream_reader(raw, closefd=False)

        try:
            with tarfile.open(fileobj=stream, mode="r|") as tf:
                for info in tf:
                    m = _Member(
                        info.name.replace("\\", "/").rstrip("/"), 
                        info, 
                        info.size, 
                        0, 
                        (
                            "dir" if info.isdir() else "file" 
                            if info.isfile() else "symlink" 
                            if info.issym() else "hardlink" 
                            if info.islnk() else "other"
                        ), 
                        info.linkname or None
                    )

                    target = self._place(m)

                    if target is None:
                        continue

                    if m.kind == "dir":
                        self._mkdir(target)
                    elif not self._mkdir(target.parent):
                        continue
                    elif m.kind != "file":
                        self._link(m, target)
                    elif (data := tf.extractfile(m.raw)) is not None:
                        self._spill(m, data, target)
        finally:
            try:
                stream.close()
            finally:
                if raw is not None:
                    raw.close()

    def _is_safe_member_name(self, name: object) -> bool:
        """Whether an archive member's name is one that may be written at all.

        Takes the name as a posix path -- "/" separated, no trailing slash
        -- which is the one spelling the read loops in _zip and _tar build.
        It does not normalise: a backslash reaching here is an ordinary
        character, and a loop that skipped its own replace() would be
        handing this a name it cannot judge.

        A name that is absolute in any spelling, or that climbs out with "..",
        is refused outright. There is no policy for it and no repair: tar strips
        the leading separator and keeps such a member, but that silently
        rewrites what the archive asked for, and an archive asking to write
        outside the directory it was given has not earned the benefit of the
        doubt on its other names either.

        Every segment is then required to be a real name -- neither ".." nor
        empty. Refusing the empty one is not fussiness about a doubled slash:
        "a//b.txt" would otherwise register a directory literally named "a/" in
        _Limiter.count, costing an entry against max_dir_entries that nothing
        will ever create, and put that same "a/" to dir_check and to
        _Filter.enter. Everything downstream reads a name as split("/") and
        expects names back; this is what makes that true.

        Each segment is stripped before it is judged, because Windows drops a
        trailing space or dot rather than storing it: ".. /x" is a directory
        called ".. " on POSIX and is "../x" on Windows. "." is left alone --
        it goes nowhere, resolve() folds it, and "./" is how tar spells the
        root of nearly every archive anyone has ever made.

        A backslash is refused outright rather than treated as a name a posix
        path may legally contain. It is what makes the precondition enforced
        instead of merely stated, and the directory cache in _Extractor._place
        depends on it: that path joins the basename onto an already-resolved
        directory and skips the resolve, which is only sound while a basename
        cannot carry a separator. Windows counts a backslash as one, so "..\\escape.txt" would
        arrive as a single segment this function would have called a name, and
        be joined into dest/../escape.txt and written outside the destination.
        The readers replace backslashes before building a _Member, so nothing
        real is turned away by this.

        Textual, and deliberately so. It is the half of the naming check that
        does not depend on what is on disk, which is what lets it run while the
        manifest is being read rather than while it is being written. The other
        half is _Extractor._place.
        """

        is_safe = bool(
            isinstance(name, str) and name
            and "\x00" not in name
            and "\\" not in name
            and not name.startswith("/")
            and not ntpath.splitdrive(name)[0]
            and not any(part.strip() in ("..", "") for part in name.split("/"))
        )

        if not is_safe:
            log.warning("extract_archive: refused unsafe member name %r in %s", name, self.src.name)

        return is_safe

    




