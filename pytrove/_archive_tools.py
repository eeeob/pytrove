"""Walking, filtering and archive-assembly internals for archive_tools.

Kept out of archive_tools.py the same way _files_tools/_async_tools are:
nothing here imports back into the package beyond typings/enums, so it can
never take part in an import cycle.
"""

import gzip
import logging
import os
import shutil
import tarfile
import zlib
import zipfile

from concurrent.futures import Executor, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import (
    Any, Callable, FrozenSet,
    Literal, Optional, Tuple, Union,
    Iterator, NamedTuple,
    TypeAlias, Iterable,
    TYPE_CHECKING,
)

from .iter_tools import dedupe
from .enums import ArchiveFormat
from .errors import ValidationError


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
    import pathspec
except ImportError:
    if not TYPE_CHECKING:
        pathspec = None


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
_Rule: TypeAlias = Union[str, Callable[[str, Any], bool]]

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
    funcs: Tuple[Callable[[str, Any], bool], ...] = ()
    names: FrozenSet[str] = frozenset()
    globs: Tuple[str, ...] = ()
    spec: Optional["pathspec.PathSpec[pathspec.GitIgnoreSpec]"] = None

    def __bool__(self):
        # Not cached: a NamedTuple hashes by content, and pathspec.PathSpec
        # defines __eq__ without __hash__, so any side carrying a glob is
        # unhashable and @cache raises TypeError on it.
        return bool(
            self.paths or
            self.funcs or
            self.names or
            self.globs or
            self.spec
        )

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
            None if pathspec is None or not globs
            else pathspec.PathSpec.from_lines("gitignore", (("\\" + g if g[:1] in ("#", "!") else g) for g in globs))
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
    def from_rules(cls, include: Iterable[_Rule], exclude: Iterable[_Rule],
                   who: str = "compress_folder") -> "_Filter":
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

    def matches(self, rel: str, entry: Optional[os.DirEntry] = None) -> bool:
        """Whether the entry at `rel` belongs in the archive.

        The ladder, walked from the top: the first rung that matches is the
        whole answer and nothing below it is consulted. That order is the
        precedence rule and the cost model at once -- a hash lookup, then
        the caller's own callables, then another hash lookup, then pattern
        matching -- so the common answers are also the early ones.

        `entry` is whatever the caller is looking at: an os.DirEntry on a
        walk, a ZipInfo or TarInfo on an extraction. Only the predicate
        rung uses it, and it is passed straight through, so a rule can ask
        about the thing itself -- its size, its mtime, whether it is a
        directory -- rather than only about its name. A caller with nothing
        to hand over leaves it out.

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
            if fn(rel, entry):
                return True
        for fn in exc.funcs:
            if fn(rel, entry):
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

    def enter(self, rel: str, entry: Optional[os.DirEntry] = None) -> bool:
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
            if fn(rel, entry):
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

        if workers or executor:
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


#: Policies, all deny-by-default. The unsafe answer to each is a decision
#: about somebody else's filesystem -- a symlink member can point anywhere,
#: a hardlink can reach a file the archive never carried -- so it has to be
#: asked for by name rather than arrived at.
_LinkPolicy: TypeAlias = Literal["allow", "skip", "error"]
_Overwrite: TypeAlias = Literal["error", "skip", "overwrite"]
_Duplicates: TypeAlias = Literal["skip", "error"]
_Mode: TypeAlias = Literal["streaming", "validate_first"]


class Limits(NamedTuple):
    """What an extraction may write, and what it may write it as.

    The five ceilings are None by default, meaning no ceiling. A library
    that started refusing archives it used to accept would break working
    code, and there is no honest number anyway: 500 MB is paranoid for a
    backup and reckless for an upload. extract_archive documents the risk
    and the caller picks.

    max_ratio is the zip bomb check: a member declaring far more bytes than
    it stores is the whole of that attack. 42.zip fits in 42 KB and claims
    4.5 PB, a ratio near 10**11. Legitimate ratios above 1000 do occur (a
    large file of zeros), so the number is a policy, not a fact.

    The four policies are not like the ceilings: each defaults to the safe
    answer rather than to none. "skip" leaves the member out and logs it,
    "error" stops the extraction with ArchivePolicyError.

    What is *not* here is any say over a member's name. A name that is
    absolute, or that climbs out with "..", is refused and logged whatever
    the settings -- see _Extractor._target. Writing where such a name asks
    to go is the vulnerability this module exists to prevent, and an option
    is only worth having where both answers are defensible.

    `mode` is when the decisions happen rather than what they are.
    "streaming" writes each member as it is read. "validate_first" reads
    the whole archive and settles every check before writing anything, so a
    breach part-way through leaves nothing behind -- at the cost of reading
    the archive twice.
    """

    max_files: Optional[int] = None
    max_total_size: Optional[int] = None
    max_file_size: Optional[int] = None
    max_ratio: Optional[float] = None
    max_depth: Optional[int] = None

    symlinks: _LinkPolicy = "skip"
    hardlinks: _LinkPolicy = "skip"
    overwrite: _Overwrite = "overwrite"
    duplicates: _Duplicates = "skip"
    mode: _Mode = "streaming"

    @classmethod
    def permissive(cls, **kw) -> "Limits":
        """Links restored, for an archive whose maker you are.

        Only what can be made safe is relaxed: a link is still refused if
        it points outside the destination, because a link that escapes is
        not one the archive was entitled to ask for. The ceilings are
        untouched -- pass them if you want them.
        """

        return cls(symlinks="allow", hardlinks="allow", **kw)


NO_LIMITS = Limits()


class _Member(NamedTuple):
    """One archive entry, in the single shape the pipeline understands.

    zipfile and tarfile describe a member so differently that every check
    downstream would otherwise be written twice. Reading both into this
    first is what leaves one admit-and-write loop instead of two.

    `raw` is the ZipInfo or TarInfo it came from, and is what a predicate
    rule is handed, so a rule can still ask whatever the container records
    beyond the fields named here. `packed` is 0 where the container has no
    per-member compressed size, which is every tar.
    """

    name: str
    raw: Any
    size: int
    packed: int
    kind: str
    target: Optional[str] = None


class _Budget:
    """Applies the ceilings to members as they are admitted.

    Checked per member and cumulatively, from the archive's own headers,
    before any of that member's bytes reach the disk -- so a bomb is
    stopped at the member that proves it rather than after the filesystem
    is full. The sizes come from headers an attacker also controls, but
    lying there is self-defeating: understate a size and the extractor
    writes only what it was told to.

    It counts what is actually being written, not what the archive holds:
    a member the filter dropped costs nothing against max_total_size,
    because the caller never asked for it.
    """

    def __init__(self, limits: "Limits", src: Path) -> None:
        self.limits = limits
        self.src = src
        self.files = 0
        self.total = 0

    def check(self, name: str, size: int, packed: int) -> None:
        lim = self.limits

        if lim.max_depth is not None and name.count("/") > lim.max_depth:
            self._fail(f"member {name!r} is nested {name.count('/')} deep, "
                       f"over the {lim.max_depth} allowed")

        if lim.max_file_size is not None and size > lim.max_file_size:
            self._fail(f"member {name!r} is {size} bytes, over the "
                       f"{lim.max_file_size} allowed")

        if lim.max_ratio is not None and packed > 0:
            ratio = size / packed

            if ratio > lim.max_ratio:
                self._fail(f"member {name!r} expands {ratio:.0f}x "
                           f"({packed} -> {size} bytes), over the "
                           f"{lim.max_ratio:g}x allowed")

        self.files += 1
        self.total += size

        if lim.max_files is not None and self.files > lim.max_files:
            self._fail(f"archive holds more than the {lim.max_files} members allowed")

        if lim.max_total_size is not None and self.total > lim.max_total_size:
            self._fail(f"archive expands past the {lim.max_total_size} bytes allowed")

    def _fail(self, why: str) -> None:
        from .errors import ArchiveLimitError

        log.warning("extract_archive: refused %s (%s)", self.src.name, why)

        raise ArchiveLimitError(f"extract_archive: {self.src.name}: {why}")


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
    into _Member, and from there every member goes through the same three
    questions -- where may it go, may it be written, and how much has been
    written already -- so a rule proved on a zip holds on a tar.

    The state is per-extraction rather than per-member, and all of it is
    the same shape: an answer keyed on a member's directory part. Members
    of one directory arrive together in every archive, so the answer wanted
    is almost always the one just stored.
    """

    src: Path
    dest: Path
    flt: "_Filter"
    limits: "Limits" = NO_LIMITS
    _root: Path = None                              # type: ignore[assignment]
    _budget: "_Budget" = None                       # type: ignore[assignment]
    _cleared: dict = field(default_factory=dict)
    _ancestry: dict = field(default_factory=dict)
    _seen: set = field(default_factory=set)
    _made: set = field(default_factory=set)

    # --- entry points ----------------------------------------------------

    def run(self, fmt: ArchiveFormat, workers=None, atomic: bool = False) -> None:
        """Extract, optionally through a staging directory.

        `atomic` writes into a sibling temp directory and moves it into
        place only once everything has been written, so a breach part-way
        through leaves the destination as it was rather than half-filled.

        The move is one rename when the destination does not yet exist,
        which is genuinely instantaneous. When it does exist there is no
        portable way to swap two directories in one step -- os.replace onto
        an existing directory fails on Windows even when it is empty -- so
        the old one is moved aside first and there is a brief moment with
        nothing at the destination. The old one is removed only after the
        new one is in place, so an interruption leaves it recoverable
        beside the destination rather than lost.
        """

        staged = (self.dest.parent / f".{self.dest.name}.{os.urandom(4).hex()}.tmp"
                  if atomic else None)

        self._reset(staged or self.dest)
        self._root.mkdir(parents=True, exist_ok=True)

        try:
            if fmt is ArchiveFormat.ZIP:
                self._zip(workers)
            else:
                self._tar(fmt, workers)
        except BaseException:
            if staged is not None:
                shutil.rmtree(staged, ignore_errors=True)
            raise

        if staged is not None:
            self._commit(staged)

    def _reset(self, root: Path) -> None:
        """Point at `root` and forget everything decided about another one."""

        self._root = root
        self._budget = _Budget(self.limits, self.src)
        self._cleared.clear()
        self._ancestry.clear()
        self._seen.clear()
        self._made.clear()

    def _commit(self, staged: Path) -> None:
        if not self.dest.exists():
            os.replace(staged, self.dest)
            return

        attic = self.dest.with_name(f".{self.dest.name}.{os.urandom(4).hex()}.old")
        os.replace(self.dest, attic)

        try:
            os.replace(staged, self.dest)
        except OSError:
            os.replace(attic, self.dest)
            raise

        shutil.rmtree(attic, ignore_errors=True)

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

    @staticmethod
    def _resolve_under(dest: Path, name: str) -> Optional[Path]:
        """Join `name` onto `dest`, resolve it, and refuse anything outside.

        resolve() does three things at once: folds "..", follows any symlink
        that already exists inside `dest`, and normalises the separators and
        the case the platform normalises. A name that climbs out therefore
        shows up as a path `dest` is not a parent of, however the climb was
        spelled -- "..", a UNC prefix, mixed slashes, or a symlink planted
        by an earlier member.

        strict=False because the target does not exist yet; it is about to
        be created. `dest` is already resolved by the caller, so this is
        resolved against resolved. is_relative_to rather than a string
        prefix, because "/tmp/dest-x" starts with "/tmp/dest" as text while
        being a different directory.
        """

        try:
            target = (dest / name).resolve()
        except (OSError, ValueError):
            # ValueError: a NUL byte, or a name Windows refuses to parse at
            # all. Either way it is not a path this can write to.
            return None

        return target if target.is_relative_to(dest) else None

    def _target(self, name: str) -> Optional[Path]:
        """Where `name` goes under the root, or None if it may go nowhere.

        A name that is absolute in any spelling, or that climbs out with
        "..", is refused outright. There is no policy for it and no repair:
        tar strips the leading separator and keeps such a member, but that
        silently rewrites what the archive asked for, and an archive that
        asks to write outside the directory it was given is not one whose
        other names deserve the benefit of the doubt either.

        Everything else goes through the directory cache. A basename
        carries no separator, so it cannot climb out of a directory already
        cleared: resolving the directory once and joining the name onto it
        gives the same answer for a fraction of the resolve() calls, which
        on Windows walk up until something exists and measured a third of
        the whole extraction.
        """

        clean = name.replace("\\", "/")

        if (not clean.strip("/") or clean.startswith("/")
                or (len(clean) > 1 and clean[1] == ":")):
            return None

        parent, _, base = clean.rpartition("/")

        # A trailing dot or space is stripped by Windows rather than stored,
        # so such a name has no faithful target and only the full resolve
        # notices; POSIX takes it literally and allows it.
        if base and base not in (".", "..") and not base.endswith((".", " ")):
            if parent not in self._cleared:
                self._cleared[parent] = (self._resolve_under(self._root, parent)
                                         if parent else self._root)

            safe = self._cleared[parent]

            return None if safe is None else safe / base

        return self._resolve_under(self._root, clean)

    def _member_kept(self, name: str, raw: Any) -> bool:
        """Apply the walk's two questions to one archive member.

        An archive lists "a/b/c.txt" and never mentions "a" or "a/b", so
        there is no walk here to prune anything and nothing that would
        carry a directory's verdict down on its own. Replaying it is what
        keeps the two halves of the library saying the same thing: without
        it, exclude="docs" would empty docs/ when compressing and do
        nothing at all when extracting.
        """

        flt, seen = self.flt, self._ancestry
        head = name.rpartition("/")[0]

        if head:
            if head not in seen:
                parts = head.split("/")
                seen[head] = all(flt.enter("/".join(parts[:i]))
                                 for i in range(1, len(parts) + 1))

            if not seen[head]:
                return False

        return flt.matches(name, raw)

    # --- whether it may be written ---------------------------------------

    def _deny(self, policy: str, why: str) -> None:
        """Act on a policy that is not "allow": raise, or log and carry on."""

        if policy == "error":
            from .errors import ArchivePolicyError

            log.warning("extract_archive: refused %s (%s)", self.src.name, why)

            raise ArchivePolicyError(f"extract_archive: {self.src.name}: {why}")

        log.warning("extract_archive: skipped %s in %s", why, self.src.name)

    def _admit(self, m: _Member) -> Optional[Path]:
        """Every reason a member might not be written, in one place.

        Returns where it goes, or None when it is not being written. The
        order is cheapest-first and also refusal-first: the name is settled
        before the filter is consulted, and the filter before anything is
        counted against the ceilings, so a member the caller did not ask
        for costs nothing at all.
        """

        target = self._target(m.name)

        if target is None:
            log.warning("extract_archive: refused unsafe member name %r in %s",
                        m.name, self.src.name)
            return None

        if m.name in self._seen:
            self._deny(self.limits.duplicates, f"duplicate member {m.name!r}")
            return None

        self._seen.add(m.name)

        if self.flt and not self._member_kept(m.name, m.raw):
            return None

        if m.kind == "other":
            log.warning("extract_archive: refused non-regular member %r in %s",
                        m.name, self.src.name)
            return None

        if m.kind == "dir":
            return target

        if target.exists() and self.limits.overwrite != "overwrite":
            self._deny(self.limits.overwrite, f"member {m.name!r} already exists")
            return None

        if m.kind == "file":
            self._budget.check(m.name, m.size, m.packed)

        return target

    # --- writing it ------------------------------------------------------

    def _mkdir(self, path: Path) -> None:
        if path not in self._made:
            path.mkdir(parents=True, exist_ok=True)
            self._made.add(path)

    def _put(self, m: _Member, target: Path, data) -> None:
        """Write one admitted member, whatever kind it turned out to be."""

        if m.kind == "dir":
            self._mkdir(target)
            return

        if m.kind in ("link", "hard"):
            self._link(m, target)
            return

        self._mkdir(target.parent)

        with open(target, "wb") as out:
            if isinstance(data, bytes):
                out.write(data)
            else:
                shutil.copyfileobj(data, out)

    def _link(self, m: _Member, target: Path) -> None:
        """Recreate a link member, if the policy allows and it stays inside.

        Two separate questions. The policy is the caller's, and defaults to
        skipping: an ordinary tarball is full of links, and a library that
        started creating them would change what installing it does.

        Containment is not the caller's. A symlink is resolved relative to
        its own directory and a hardlink relative to the archive root, and
        either way a link landing outside the destination is refused
        whatever the policy says -- a later member written "through" it
        would escape even though its own name looked harmless, which is the
        whole reason link members are dangerous.
        """

        kind = "symlink" if m.kind == "link" else "hardlink"
        policy = self.limits.symlinks if m.kind == "link" else self.limits.hardlinks

        if policy != "allow":
            self._deny(policy, f"{kind} member {m.name!r}")
            return

        raw = m.target or ""
        base = target.parent if m.kind == "link" else self._root

        try:
            resolved = (base / raw).resolve()
        except (OSError, ValueError):
            resolved = None

        if resolved is None or not resolved.is_relative_to(self._root):
            log.warning("extract_archive: refused %s %r pointing outside %s in %s",
                        kind, m.name, self.dest.name, self.src.name)
            return

        self._mkdir(target.parent)

        try:
            if m.kind == "link":
                os.symlink(raw, target)
            else:
                os.link(resolved, target)
        except OSError as exc:
            # Creating a symlink needs a privilege on Windows that an
            # ordinary account does not hold, and a hardlink needs the
            # target to exist and to share a volume.
            log.warning("extract_archive: could not create %s %r (%s)", kind, m.name, exc)

    # --- reading the two containers --------------------------------------

    @staticmethod
    def _zip_members(zf: zipfile.ZipFile) -> Iterator[_Member]:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            kind = "dir" if info.is_dir() else "file"

            # The unix mode lives in the top half of external_attr, and
            # S_IFLNK there is how a zip records a symlink. Most zips
            # written on Windows carry no mode at all, which reads as 0.
            mode = info.external_attr >> 16

            if kind == "file" and mode and (mode & 0o170000) == 0o120000:
                kind = "link"

            yield _Member(name.strip("/") if kind != "dir" else name.rstrip("/"),
                          info, info.file_size, info.compress_size, kind)

    @staticmethod
    def _tar_members(tf: tarfile.TarFile) -> Iterator[_Member]:
        for info in tf:
            if info.isdir():
                kind = "dir"
            elif info.isfile():
                kind = "file"
            elif info.issym():
                kind = "link"
            elif info.islnk():
                kind = "hard"
            else:
                kind = "other"

            # A tar member is stored uncompressed inside one stream, so
            # there is no per-member compressed size to take a ratio
            # against. The whole-archive ceilings still apply, and the
            # stream's own compression is bounded by max_total_size.
            yield _Member(info.name.replace("\\", "/").strip("/"),
                          info, info.size, 0, kind, info.linkname or None)

    @contextmanager
    def _stream(self, fmt: ArchiveFormat):
        """Open the tar, through whichever decompressor `fmt` names."""

        raw = open(self.src, "rb") if fmt is ArchiveFormat.TAR_ZST else None

        if raw is None:
            stream = gzip.open(self.src, "rb")
        elif std_zstd is not None:
            stream = std_zstd.ZstdFile(raw, "rb")
        else:
            stream = zstandard.ZstdDecompressor().stream_reader(raw, closefd=False)

        try:
            with tarfile.open(fileobj=stream, mode="r|") as tf:
                yield tf
        finally:
            stream.close()

            if raw is not None:
                raw.close()

    @staticmethod
    def _blob(fp, info: zipfile.ZipInfo) -> bytes:
        # The local header's length varies with the name and extra field, so
        # the data offset can only be found by reading it -- the central
        # directory records where the header starts, not where the data does.
        fp.seek(info.header_offset)
        head = fp.read(30)
        fp.seek(info.header_offset + 30
                + int.from_bytes(head[26:28], "little")
                + int.from_bytes(head[28:30], "little"))

        return fp.read(info.compress_size)

    @staticmethod
    def _inflate(info: zipfile.ZipInfo, blob: bytes) -> bytes:
        return (zlib.decompress(blob, -15)
                if info.compress_type == zipfile.ZIP_DEFLATED else blob)

    # --- the two containers ----------------------------------------------

    def _zip(self, workers=None) -> None:
        """Admit every member from the central directory, then write.

        The whole manifest is known before anything is written -- infolist()
        reads the central directory, not the data -- so on a zip every
        check is settled first whatever `mode` says. What "validate_first"
        adds here is the checksums, which cost a full read of the archive.

        The compressed bytes are lifted out of the file directly rather
        than through ZipFile.open, so a member's declared size and ratio
        are judged from its header before anything is inflated.
        Decompressing first and checking afterwards is how a bomb wins.

        `workers` is worth having on a zip and on nothing else: members are
        compressed independently, and zlib releases the GIL while
        inflating. Reading stays on this thread because there is one file
        handle; only the inflate and the write go to the pool. A member's
        compressed bytes are held from the read until a worker takes them,
        so the pool trades memory for time.
        """

        count, pool = _split_workers(workers, "extract_archive")

        with zipfile.ZipFile(self.src) as zf:
            if self.limits.mode == "validate_first":
                bad = zf.testzip()

                if bad is not None:
                    raise ValidationError(
                        f"extract_archive: {self.src.name}: member {bad!r} "
                        f"failed its checksum"
                    )

            plan = [(m, t) for m in self._zip_members(zf)
                    if (t := self._admit(m)) is not None]

            for m, t in plan:
                if m.kind != "file":
                    self._put(m, t, None)

            files = [(m, t) for m, t in plan if m.kind == "file"]
            fp = zf.fp
            own = ThreadPoolExecutor(count) if count and count > 1 else None
            pool = pool or own
            pending = []

            try:
                for m, t in files:
                    self._mkdir(t.parent)
                    blob = self._blob(fp, m.raw)

                    if pool is None:
                        t.write_bytes(self._inflate(m.raw, blob))
                    else:
                        pending.append(pool.submit(self._write_one, m.raw, t, blob))

                for job in pending:
                    job.result()
            finally:
                if own is not None:
                    own.shutdown()

    def _write_one(self, info: zipfile.ZipInfo, target: Path, blob: bytes) -> None:
        target.write_bytes(self._inflate(info, blob))

    def _tar(self, fmt: ArchiveFormat, workers=None) -> None:
        """Read the tar stream and write every member that passes.

        A tar is one stream that can only be read in order, so there is
        nothing here to parallelise; `workers` is reported rather than
        quietly dropped.

        "validate_first" costs a second pass, because a stream cannot be
        rewound. The first reads every admitted member to the end, which is
        what makes a truncated archive or a bad checksum surface, and the
        second writes -- so nothing is on disk when the archive turns out
        to be broken half-way through.
        """

        if workers:
            log.warning(
                "extract_archive: a tar is one stream and cannot be read in "
                "parallel, so workers was ignored and this ran on the calling "
                "thread. Only ZIP can use it."
            )

        if self.limits.mode == "validate_first":
            with self._stream(fmt) as tf:
                for m in self._tar_members(tf):
                    if self._admit(m) is None or m.kind != "file":
                        continue

                    handle = tf.extractfile(m.raw)

                    while handle is not None and handle.read(1 << 20):
                        pass

            self._reset(self._root)

        with self._stream(fmt) as tf:
            for m in self._tar_members(tf):
                target = self._admit(m)

                if target is None:
                    continue

                data = tf.extractfile(m.raw) if m.kind == "file" else None

                if m.kind == "file" and data is None:
                    continue

                self._put(m, target, data)
