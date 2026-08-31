"""Walking, filtering and archive-assembly internals for archive_tools.

Kept out of archive_tools.py the same way _files_tools/_async_tools are:
nothing here imports back into the package beyond typings/enums, so it can
never take part in an import cycle.
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
import io

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

_WalkEntry: TypeAlias = Tuple[str, str, bool]
_RawEntry: TypeAlias = Optional[Union["os.DirEntry", zipfile.ZipInfo, tarfile.TarInfo]]
_Rule: TypeAlias = Union[str, Callable[[str, _RawEntry], bool]]

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

    @staticmethod
    @lru_cache(maxsize=256, typed=True)
    def sort(items: Iterable[_Rule]) -> _Rules:
        """Sort one side's rules onto their rungs, keyed on the set itself.

        Cached because a walk asks the same two sets about every entry in
        the tree, and sorting is pure: the same set always gives the same
        answer. A frozenset hashes by content, so a caller passing the
        same rules again hits the cache without having kept anything
        alive.

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
            if fn(rel, raw):
                return True
        for fn in exc.funcs:
            if fn(rel, raw):
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
            if fn(rel, raw):
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
                entries = list(os.scandir(current))
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

    def _write_zip(self, out, level, workers, executor, _use_fastzip=False) -> None:
        """Write every walked entry into a zip container."""

        entries = iter(self)

        if (workers or 0) > 1 or executor is not None:
            if WZip is None:
                log.warning(
                    "compress_folder: workers requested but fastzip is not available, "
                    "compressing on this thread instead. Install it with: "
                    "pip install 'pytrove[fastzip]'"
                )
            else:
                _use_fastzip = True


        if _use_fastzip:
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
                if is_dir and _use_fastzip:
                    continue

                try:
                    if _use_fastzip:
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

        with compressor as stream, tarfile.open(fileobj=stream, mode="w|") as tf:
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



_COPY_BUF = 1 << 20
_LINK_MAX = 4096



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

        A second call is refused rather than served. The object holds a
        destination it has already resolved paths against and a _Limiter
        that has already spent its ceilings, and reusing it would either
        answer the second archive with the first one's state or need every
        field cleared -- which is a fresh object with extra steps. This
        class is cheap to build; extract_archive builds one per call.

        `atomic` writes into a sibling temp directory -- a sibling because
        the last step is a rename and a rename does not cross a filesystem
        -- and moves it into place only once everything has been written,
        so a breach part-way through leaves the destination as it was
        rather than half-filled.

        The move is one rename when the destination does not yet exist,
        which is genuinely instantaneous. When it does exist there is no
        portable way to swap two directories in one step -- os.replace onto
        an existing directory fails on Windows even when it is empty -- so
        the old one is moved aside first and there is a brief moment with
        nothing at the destination. The old one is removed only after the
        new one is in place, so an interruption leaves it recoverable
        beside the destination rather than lost.

        `cleanup_on_error` is the same promise made without a staging
        directory: whatever this run created is removed again if it does
        not finish. It is off by default, because a half-extracted tree is
        sometimes the useful thing -- what came out before the archive
        turned out to be wrong -- and deleting it is not a decision to make
        on the caller's behalf.

        What it undoes is only what this run made. Every file written and
        every directory that was not already there goes into a ledger as it
        is created, and the ledger is walked backwards, so a directory
        removed is one this run created and nothing that was in `dest`
        beforehand is ever touched. It does nothing under `atomic`, or with
        a dir_check set, since both stage already and the staging directory
        is discarded whole.

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

        self._root.mkdir(exist_ok=True)

        try:
            if fmt is ArchiveFormat.ZIP:
                self._zip(workers)
            else:
                self._tar(fmt, workers)

            self._inspect(self._root)
        except:
            if staged is not None:
                remove_path(staged)
            elif self._built:
                for path in dedupe(self._built or ()):
                    safe_call(remove_path, path, include_exc=OSError, log_exc=True)
            raise

        if staged is not None:
            if not self.dest.exists() or not any(self.dest.iterdir()):
                os.replace(staged, self.dest)
            else:
                try:
                    self._graft(staged, self.dest)
                finally:
                    remove_path(staged)

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

        stack = [root]

        while stack:
            try:
                entries = list(os.scandir(stack.pop(0)))
            except OSError as exc:
                log.warning("extract_archive: cannot read back %r (%s)", root, exc)
                continue

            for entry in entries:
                if not entry.is_dir(follow_symlinks=False):
                    continue

                path = Path(entry.path)

                if self._limiter.allows_dir(path):
                    stack.append(path)
                else:
                    remove_path(path)

    @classmethod
    def _graft(cls, staged: Path, dest: Path) -> None:
        """Move everything in `staged` into `dest`, directory by directory.

        A directory that exists on both sides is descended into rather than
        replaced, which is the whole of what "merge" means here: it is what
        keeps a file the archive never mentioned. Anything else is moved
        over what is there, which is what a non-staged run does when it
        writes onto an existing name -- and `overwrite` has already had its
        say about this exact path, because _place asks about where the
        member lands rather than about the staging directory.

        A destination entry that is a symlink is never descended into, even
        when it points at a directory. Following one would move members
        outside the destination, which is the single thing this class
        exists to prevent; it is replaced like any other member instead.
        """

        for entry in os.scandir(staged):
            target = dest / entry.name

            if entry.is_dir(follow_symlinks=False) and target.is_dir() and not target.is_symlink():
                cls._graft(Path(entry.path), target)
                continue

            if target.is_symlink() or target.exists():
                remove_path(target)

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

        lower = path.lower()

        for suffix, fmt in ((".zip", ArchiveFormat.ZIP),
                            (".tar.zst", ArchiveFormat.TAR_ZST),
                            (".tar.gz", ArchiveFormat.TAR_GZ),
                            (".tgz", ArchiveFormat.TAR_GZ)):
            if lower.endswith(suffix):
                return fmt

        raise ValueError(f"extract_archive: cannot tell what format {path!r} is")

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

        Most names go through the directory cache. A basename carries no
        separator -- the name check refuses one that does -- so it cannot
        climb out of a directory already cleared: resolving the directory
        once and joining the name onto it gives the same answer for a
        fraction of the resolve() calls, which on Windows walk up until
        something exists and measured a third of the whole extraction. A
        trailing dot or space is the exception, because Windows strips one
        rather than storing it, so such a name has no faithful target and
        only the full resolve notices; POSIX takes it literally.
        """

        parent, _, base = name.rpartition("/")

        if base.endswith((".", " ")):
            target = (
                _target 
                if (
                    (_target := safe_call((self._root / name).resolve, strict=False, include_exc=(ValueError, OSError), log_exc=True)) is not None
                    and _target.is_relative_to(self._root) 
                )
                else None
            )
        else:
            if parent not in self._cleared:
                self._cleared[parent] = (
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

            target = None if (safe := self._cleared[parent]) is None else safe / base

        return target

    # --- whether it may be written ---------------------------------------

    def _place(self, m: _Member) -> Optional[Path]:
        """Where this member goes, or None if it is not to be written.

        Called one member ahead of its own write, and the whole of what
        stands between an archive's word and a path on disk. Two halves,
        in this order and not the other.

        The first is answered from the archive's own account of the member
        and touches no filesystem: the name, the duplicates, the filter,
        the kind, the ceilings. It is ordered cheapest-first and
        refusal-first at once -- the name before the filter, the filter
        before anything is counted -- so a member the caller did not ask
        for costs nothing at all against the ceilings.

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
            not self._is_safe_member_name(name) or
            not self._limiter.allows_name(name) or 
            (self.flt and not self._member_kept(m))
        ):
            return 

        self._limiter.count(m)

        # --- and what the filesystem says -------------------------------

        target = self._under(name)

        if target is None:
            log.warning("extract_archive: refused member %r in %s, it resolves outside the destination", name, self.src.name)
            return 

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

        fresh = []

        if self._built is not None:
            probe = path

            while probe != self._root and probe != probe.parent and not probe.exists():
                fresh.append(probe)
                probe = probe.parent

        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("extract_archive: cannot create directory %r in %s (%s)", str(path), self.src.name, exc)
            return False

        self._made.add(path)

        if fresh:
            # `fresh` was collected child-first on the way up, so it goes
            # in outermost-first -- the order _undo relies on.
            self._built.extend(reversed(fresh))

        return True

    def _link(self, m: _Member, target: Path) -> None:
        """Recreate a link member, if the policy allows and it stays inside.

        Two separate questions, and only one of them is the caller's. The
        policy is -- `symlinks` and `hardlinks`, asked of the limiter, which
        logs or raises on its own. `overwrite` is the caller's too, and was
        answered in _place like any other member; what is left here is
        carrying that answer out, since a link cannot be written over the
        way a file can.

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

        remove_path(target)

        try:
            if m.kind == "symlink":
                os.symlink(raw, target)
            else:
                os.link(resolved, target)
        except OSError as exc:
            # Creating a symlink needs a privilege on Windows that an
            # ordinary account does not hold, and a hardlink needs the
            # target to exist and to share a volume.
            log.warning("extract_archive: could not create %s %r (%s)", m.kind, m.name, exc)
        else:
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
        _zip never hands a link to the pool, so _link still runs on the
        main thread, which is what keeps the directory cache and the ledger
        single-threaded.

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
        directory, so the only thing a worker touches is its own member.
        """

        count, pool = _split_workers(workers, "extract_archive")
        own = ThreadPoolExecutor(count) if count and count > 1 else None
        pool = pool or own
        readers = _ZipReaders(self.src, self.password)
        inflight = {}          #: path -> the write filling it

        try:
            for info in readers.get().infolist():
                m = _Member(
                    info.filename.replace("\\", "/").rstrip("/"), 
                    info, 
                    info.file_size, 
                    info.compress_size, 
                    (
                        "dir" if info.is_dir() else "symlink"
                        if ((mode := info.external_attr >> 16) and stat.S_ISLNK(mode)) else "file" 
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
                    key = os.path.normcase(str(target))

                    if (earlier := inflight.pop(key, None)) is not None:
                        earlier.result()

                    inflight[key] = pool.submit(self._zip_copy, readers, m, target)

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

                    if m.kind == "other":
                        log.warning("extract_archive: refused non-regular member %r in %s", m.name, self.src.name)
                        continue

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
            log.warning("refused unsafe member name %r in %s", name, self.src.name)

        return is_safe

    




