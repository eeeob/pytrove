import sys

if sys.version_info >= (3, 11):
    from typing import Unpack
else:
    from typing_extensions import Unpack

from typing import (
    Any, List, Union, Optional,
    Literal, cast, overload,
)

from pathlib import Path
from contextlib import contextmanager

from .typings import (
    JsonValue, NestedContainer, PathLike, LockProtocol,
    _True, _False, _T,
)
from .enums import PickleSafety, TruncateSide
from .errors import ValidationError
from .callable_tools import safe_call
from .iter_tools import iter_flat_cont, to_frozenset
from ._optional import _optional_import
from ._files_tools import (
    _MkdirOptions, 
    _RestrictedUnpickler, 
    _COPY_BUF, 
    _NOT_SET, 
    _SPILL_PARTS, 
    _SAFE_PICKLE_CLASSES, 
    _is_link, 
    _is_dir, 
    _next_part, 
    _json_dumps, 
    _json_loads, 
)

import io
import logging
import math
import os
import shutil
import pickle
import tempfile



try:
    import jsonref
except ImportError:
    pass


log = logging.getLogger(__name__)


def ensure_path(path: PathLike) -> Path:
    if not isinstance(path, Path):
        path = Path(path)
    return path

def resolve_path(path: PathLike, strict: bool = False) -> Path:
    return ensure_path(path).resolve(strict=strict)

def ensure_dir(path: PathLike, for_file: bool = False, **kwargs: Unpack[_MkdirOptions]) -> Path:
    """Create a directory and hand `path` straight back, as a Path.

    Returning the argument rather than the directory is what makes this
    usable inline, which is the whole point of it:

        write_file(ensure_dir(out / "2024" / "log.txt", for_file=True), text)
        archive = compress_folder(src, ensure_dir(backups))

    `for_file` says which of the two a path is, because nothing else can:
    a path that has not been created yet is neither a file nor a directory
    on disk, and an extension does not decide it -- "README" and
    ".gitignore" have none, and "cache.d" is a directory in plenty of
    trees. So it is stated rather than guessed. False, the default, means
    `path` is the directory to create; True means it names a file, and the
    directory to create is the one above it. Either way what comes back is
    `path` itself, so the file case returns a path that does not exist yet
    and is now writable.

    Everything else goes to Path.mkdir untouched -- `mode`, `parents`
    and `exist_ok` -- typed key by key, so a misspelled `parent` or a
    `mode="755"` is caught where it is written rather than arriving as a
    TypeError from inside mkdir. Forwarded rather than restated, so a
    keyword the stdlib adds is one line away and this signature does not
    move.

    Two of them start from the opposite end, and only their defaults:
    mkdir has `parents` and `exist_ok` False, and this has both True.
    "Make sure this directory is there" is what a caller wants nearly
    every time, and the strict pair is what you ask for on the rare call
    that means "and it must not have been there already". `mode` is left
    to mkdir's own default.

    Their meanings carry over exactly, and two are worth knowing:

      `mode` is masked by the process umask, so 0o777 gives 0o755 under
      the usual 0o022, and it applies only to the last component -- any
      parents that `parents` creates get the default permissions whatever
      is passed here. Windows ignores it altogether.

      `exist_ok` forgives an existing *directory* and nothing else. A file
      sitting at the path still raises FileExistsError, which is the right
      answer: the caller asked for a directory there and there is not one.

    The path is handed back exactly as given -- relative stays relative,
    and no symlink is resolved. Wrap it in resolve_path if an absolute one
    is wanted.
    """

    kwargs.setdefault("parents", True)
    kwargs.setdefault("exist_ok", True)

    path = ensure_path(path)
    (path.parent if for_file else path).mkdir(**kwargs)

    return path


def remove_files(*files: NestedContainer[PathLike]) -> None:
    for file in iter_flat_cont(files):
        try:
            os.unlink(file)
        except FileNotFoundError:
            pass
        

remove_file = remove_files


def _on_exc_remove_folders(func, path, exc_info):
    if func == os.path.islink and _is_link(path):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        return
    
    raise exc_info[1].with_traceback(exc_info[2])

def remove_folders(*folders: NestedContainer[PathLike]) -> None:
    for folder in iter_flat_cont(folders):
        try:
            shutil.rmtree(folder, onerror=_on_exc_remove_folders)
        except FileNotFoundError:
            pass
        

remove_folder = remove_folders


def remove_paths(*paths: NestedContainer[PathLike]) -> None:
    for path in iter_flat_cont(paths):
        if _is_dir(path):
            remove_folders(path)
        else:
            remove_files(path)

remove_path = remove_paths

@contextmanager
def atomic_write(
    path: PathLike,
    binary: bool = False,
    encoding: str = "utf-8",
    mode: Optional[int] = None,
    lock: Optional[LockProtocol] = None,
    fsync: bool = True,
    ):

    """Open a file for writing that only replaces `path` once the block ends.

    Yields a writable file object backed by a temp file in the same
    directory, which is os.replace()d over `path` on a clean exit -- so a
    reader never sees a partial file, and a block that raises leaves the
    previous contents untouched. The temp file is removed either way.

    Use this over write_file when the content is produced incrementally or
    is large enough that holding all of it in memory to hand over as one
    value is itself the cost -- write_pickle streams into it for exactly
    that reason. See write_file for what `fsync` buys.
    """

    path = resolve_path(path)
    directory = path.parent

    if mode is None:
        try:
            mode = path.stat().st_mode & 0o777
        except FileNotFoundError:
            mode = 0o644

    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)

    try:
        if lock is not None:
            lock.acquire()

        with os.fdopen(fd, "wb" if binary else "w", encoding=None if binary else encoding) as f:
            yield f

            if fsync:
                f.flush()
                os.fsync(f.fileno())

        # Skipped when the block raised -- the exception propagates out of
        # the yield above, so the destination is never replaced.
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)

        if fsync:
            # Persisting the file's data is not enough on its own -- the
            # rename lives in the directory, which needs its own fsync to
            # survive a power loss.
            try:
                dir_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    safe_call(os.close, dir_fd)
            except OSError:
                pass

    finally:
        try:
            if lock is not None:
                lock.release()
        finally:
            remove_file(tmp_path)


def write_file(
    path: PathLike,
    content: Union[str, bytes],
    encoding: str = "utf-8",
    mode: Optional[int] = None,
    lock: Optional[LockProtocol] = None,
    fsync: bool = True,
    ) -> None:

    """Write `content` to `path`, replacing it atomically.

    The bytes go to a temp file in the same directory, which is then
    os.replace()d over the destination -- a reader never sees a partial
    file, and an interrupted call leaves the previous contents intact.

    `fsync=True` (the default) additionally forces the data to the physical
    disk, and the rename into the directory entry along with it, before
    returning. That is what makes the write survive a power loss rather
    than only a crashed process -- and it is roughly two thirds of the cost
    of the call. Pass fsync=False for data you could afford to regenerate
    (caches, scratch files, logs): the write stays atomic either way.
    """

    with atomic_write(
        path,
        binary=isinstance(content, bytes),
        encoding=encoding,
        mode=mode,
        lock=lock,
        fsync=fsync,
    ) as f:
        f.write(content)

# Which of the two the call gets is decided by `spill`, so the literal
# has to reach the type checker: without these, every call is typed as the
# union and every caller has to narrow a value it already knows the shape
# of. Same dispatch as to_thread's `return_exc` and decrypt's.
@overload
def truncate_file(
    path: PathLike,
    size: int,
    cut: TruncateSide = ...,
    spill: _False = False,
    fsync: bool = True,
) -> Path: ...
@overload
def truncate_file(
    path: PathLike,
    size: int,
    cut: TruncateSide = ...,
    spill: Union[_True, PathLike] = ...,
    fsync: bool = True,
) -> List[Path]: ...
def truncate_file(
    path: PathLike,
    size: int,
    cut: TruncateSide = TruncateSide.HEAD,
    spill: Union[bool, PathLike] = False,
    fsync: bool = True,
    ) -> Union[Path, List[Path]]:

    """Leave `size` bytes in `path`, and return where the rest went.

    `size` is what the file is left holding, not an amount to take off it:
    a 10 KB file and size=3000 comes back 3000 bytes long, and the other
    7240 are what `spill` decides the fate of. A file already at or under
    `size` is left alone entirely.

    `cut` names the end that goes, so `size` is measured from the other
    one. HEAD is the default:

      HEAD  keep the LAST `size` bytes -- what a log wants, where the
            newest lines are the ones worth keeping. It costs a rewrite of
            the part that stays: no filesystem drops bytes off the front
            of a file in place.
      TAIL  keep the FIRST `size` bytes -- the plain truncation, and the
            cheap one, since what stays does not move.

    Either the enum or its raw string ("head", "tail") is accepted.

    `spill` decides whether the removed bytes are lost or kept. False, the
    default, discards them. True writes them beside the file, and a path
    writes them into that directory instead, creating it if it is not
    there. Either way they are split into parts of `size` bytes named
    "<file>.1", "<file>.2", ... in the order they appear in the original,
    so putting it back together is a concatenation and nothing else:

        file + part.1 + part.2 + ...   for cut=TAIL
        part.1 + part.2 + ... + file   for cut=HEAD

    size=0 is the one case that names no part size, since it keeps
    nothing in the file. The spill is cut into ten parts there instead --
    a share of what is being spilled rather than a fixed length, so a
    large file does not come back as thousands of small ones.

    Numbering continues past whatever parts are already in the directory
    rather than starting at 1, so truncating the same file twice adds
    parts instead of writing over the first set. Only an all-digit suffix
    counts as one, so "app.log.bak" is left out of the reckoning.

    The parts are written and flushed before the file is touched, so an
    interruption costs at worst some parts that duplicate bytes still in
    the file -- never bytes that are in neither. Each part is written
    through atomic_write, so a reader never sees a half-written one.

    What comes back follows the same split. Without `spill` there is only
    one file in play and its own path is the answer, the way write_file's
    and compress_folder's callers expect a path back -- there is no list to
    return, and returning an empty one said nothing. With `spill` the parts
    are the answer, in the order they were written, and an empty list means
    the file was already at or under `size` and nothing was cut.

    Note the file's identity survives a TAIL cut and not a HEAD one: HEAD
    rewrites through a rename, so the inode changes and anything holding
    the old handle -- a tail -f, a logger that kept the file open -- goes
    on writing to the file that is no longer there. Mode is preserved.

    See also atomic_write, which this uses, and write_file for replacing a
    file's contents outright rather than trimming them.
    """

    path = resolve_path(path, strict=True)
    side = TruncateSide(cut)

    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValidationError(f"truncate_file: size must be a whole number of bytes, not {size!r}")

    if not path.is_file():
        raise ValidationError(f"truncate_file: {str(path)!r} is not a file")

    total = path.stat().st_size

    if total <= size:
        return [] if spill else path

    dropped = total - size
    parts: List[Path] = []

    # Copying, not cutting. This block only ever reads `path` -- the file
    # still has every byte it started with when the block ends, and the
    # cut below is what shortens it. That order is the guarantee: the
    # parts are on disk and flushed before anything is taken away, so an
    # interruption costs a duplicate, never a loss.
    if spill:
        folder = ensure_dir(path.parent if spill is True else resolve_path(spill))

        # `size` is the part size everywhere except at 0, which keeps
        # nothing and so names no length to cut by. A tenth of what is
        # being spilled, rounded up: ten parts at most however large the
        # file is, where a fixed length would make a 4 GB file into
        # thousands of them. Rounded up rather than down for a reason --
        # a floor divides anything under ten bytes to 0, which writes no
        # part at all and then empties the file.
        #
        # math.ceil divides as a float, which is exact to 2^53 and starts
        # disagreeing with integer arithmetic from 2^54 -- measured, 16 PB
        # further along than any file this will be handed.
        part_size = size or math.ceil(dropped / _SPILL_PARTS)
        number = _next_part(folder, path.name)
        left = dropped

        with open(path, "rb") as src:
            src.seek(0 if side == TruncateSide.HEAD else size)

            while left > 0:
                want = min(part_size, left)
                part = folder / f"{path.name}.{number}"
                written = 0

                with atomic_write(part, binary=True, fsync=fsync) as out:
                    while written < want:
                        chunk = src.read(min(_COPY_BUF, want - written))

                        if not chunk:
                            break

                        out.write(chunk)
                        written += len(chunk)

                if not written:
                    # Nothing left to read: the file shrank under us, or it
                    # was never as long as its size said. The part is empty
                    # and would only be a lie about what was there.
                    remove_file(part)
                    break

                parts.append(part)
                number += 1
                left -= written

                if written < want:
                    break

    # The cut itself, and it runs whether or not anything was spilled --
    # `spill` decides what becomes of the removed bytes, not whether they
    # are removed. Neither branch re-reads what the block above read:
    # measured on a 10240-byte file cut to 3000, TAIL reads nothing at all
    # here and HEAD reads only the 3000 that stay, so with spilling on the
    # two blocks together read the file exactly once between them.
    if side == TruncateSide.TAIL:
        # In place. The bytes that stay are already where they belong, so
        # there is nothing to copy and nothing to rename.
        # os.truncate(path, size) would say this in one call and is the
        # obvious shape -- but it takes a path and hands back no
        # descriptor, and `fsync` needs one. Reopening the file purely to
        # fsync it is two syscalls to save none.
        #
        # No flush before it: nothing was written through this handle, and
        # BufferedRandom.truncate flushes on its own regardless.
        with open(path, "r+b") as f:
            f.truncate(size)

            if fsync:
                os.fsync(f.fileno())
    else:
        # atomic_write on the outside, the reader on the inside: the
        # rename cannot happen while the file it replaces is still open
        # here, which Windows refuses outright rather than deferring.
        with atomic_write(path, binary=True, fsync=fsync) as out:
            with open(path, "rb") as src:
                src.seek(dropped)

                while chunk := src.read(_COPY_BUF):
                    out.write(chunk)

    return parts if spill else path


# The binary=True overload must come first: an overload that omits `binary`
# but keeps **kw absorbs `binary=True` into kw and matches before this one
# ever gets tried, silently typing a bytes read as str.
@overload
def read_file(
    path: PathLike,
    *,
    binary: Literal[True],
    lock: Optional[LockProtocol] = None,
    **kw
) -> bytes: ...
@overload
def read_file(
    path: PathLike,
    *,
    binary: Literal[False] = False,
    encoding: str = "utf-8",
    lock: Optional[LockProtocol] = None, 
    **kw
) -> str: ...
def read_file(
    path: PathLike,
    *, 
    binary: bool = False, 
    encoding: str = "utf-8", 
    lock: Optional[LockProtocol] = None, 
    **kw
):
    """Read the file at `path`, as text by default or as bytes with
    binary=True.

    `path` is opened as given rather than resolved first -- resolving walks
    every component of the path through realpath(), which costs about as
    much again as the read itself, and open() follows symlinks and relative
    paths on its own. write_file does resolve, because it has to know the
    real parent directory to place its temp file in.
    """

    try:
        if lock is not None:
            lock.acquire()

        if binary:
            with open(path, "rb", **kw) as f:
                return f.read()

        with open(path, "r", encoding=encoding, **kw) as f:
            return f.read()
    finally:
        if lock is not None:
            lock.release()


def read_json(
    path: PathLike,
    default: _T = cast(dict, _NOT_SET),
    lock: Optional[LockProtocol] = None,
    **kw,
    ) -> Union[JsonValue, _T]:

    """Parse the JSON file at `path`, or return `default` if it is missing.

    The file is read as bytes and parsed from bytes: both json and orjson
    decode UTF-8 internally, so decoding to str first only makes a copy
    nothing reads. With the `fastjson` extra installed, a call passing no
    other kwargs is parsed by orjson instead of json.
    """

    try:
        content = read_file(path, binary=True, lock=lock)
    except FileNotFoundError:
        return {} if default is _NOT_SET else default

    return _json_loads(content, kw)

def write_json(
    path: PathLike,
    data: JsonValue,
    lock: Optional[LockProtocol] = None,
    fsync: bool = True,
    **kw,
    ) -> None:

    """Serialise `data` as JSON and write it to `path`, atomically.

    No `indent` is applied unless asked for: indenting is by far the most
    expensive thing this call does -- roughly six times the cost of the
    same dump without it, for a file three times the size. Pass `indent=2`
    (or 4) for a file a person will open and read.

    With the `fastjson` extra installed, orjson serialises instead of json
    whenever the given kwargs are expressible in it -- `ensure_ascii` false
    (its only behaviour), `indent` of None or 2, `sort_keys`, and `default`.
    That is another ~10x, so `indent=2` is worth preferring over 4 when the
    file still has to stay readable: 4 falls back to json.

    `default` behaves the same on either path: orjson would otherwise
    serialise datetimes and dataclasses itself, so those are handed to
    `default` explicitly, and raise TypeError without one, exactly as json
    does. The two paths differ only in the compact form's whitespace.

    `data` must not be mutated by another thread for the duration of the
    call. Serialising walks the structure, and what happens when it changes
    underneath depends on how the walk is implemented:

      - A dict that changes SIZE mid-walk raises RuntimeError("dictionary
        changed size during iteration"), so the write fails loudly and the
        previous file survives.
      - A list that changes does NOT raise. It is walked by index, so the
        file is written successfully containing a mix of before-state and
        after-state -- a snapshot that never existed. A shrinking list can
        also lose entries outright.

    Whether the walk is interruptible at all depends on the encoder. With
    no `indent`, json uses its C encoder and orjson is C throughout: both
    traverse without releasing the GIL, so another thread cannot interleave
    and the snapshot is effectively atomic. Passing `indent` drops json to
    its pure-Python encoder, which yields between elements and is fully
    exposed to the hazard above.

    `lock` does not help with any of this -- it guards the file, and is
    only taken once the bytes already exist. Serialise under whatever lock
    protects the structure, or hand in a copy.

    `fsync` is passed through to write_file -- see there for the durability
    it buys and what it costs.
    """

    kw.setdefault("ensure_ascii", False)

    content = _json_dumps(data, kw)
    del data
    write_file(path, content, encoding="utf-8", lock=lock, fsync=fsync)
    

load_json = read_json
save_json = write_json


def read_pickle(
    path: PathLike,
    default: _T = cast(dict, _NOT_SET),
    lock: Optional[LockProtocol] = None,
    *,
    allow_classes: Optional[NestedContainer[type]] = None,
    allow_modules: Optional[NestedContainer[str]] = None,
    safe: Union[PickleSafety, bool] = PickleSafety.STRICT,
    **kw,
    ) -> Union[Any, _T]:

    """Unpickle the object stored in the file at `path`.

    A missing file yields `default`, or `{}` when none was given -- same
    contract as read_json, so a store can be read before it has ever been
    written without guarding the call.

    Unpickling is arbitrary code execution by design: the data names the
    classes and callables to use, and plain `pickle.load` invokes whatever
    it is told to. `safe` picks how much of that to allow, as a PickleSafety
    member -- strongest first, which is also the default:

      STRICT (default)  only the inert builtin/stdlib types, plus whatever
                        `allow_classes` names. Anything else raises
                        UnpicklingError, so a tampered file fails to load
                        rather than running.
      MODULES           the above, plus anything defined in a module named
                        by `allow_modules` -- for your own app's classes in
                        bulk, without listing each one.
      BLOCKLIST         everything except the known execution vectors
                        (os/subprocess/ctypes/..., builtins.eval/exec/...).
                        Best-effort: a blocklist only refuses what it knows,
                        so this guards against accidents, not attackers.
      NONE              plain pickle, no restriction whatsoever.

    `safe=True`/`False` still work, and mean STRICT/NONE.

    `allow_classes` takes a single class, a list, or any nesting of them,
    and applies at every level; each is matched by exact module and
    qualname, so a same-named class from elsewhere is still refused. Note a
    class you allow is one you accept being constructed from file contents,
    with whatever state the file dictates -- allow only classes whose
    __setstate__/__reduce__ do nothing dangerous. `allow_modules` is the
    same trade made a whole module at a time, and only MODULES reads it.

    Anything below STRICT is a file you are vouching for. Reserve it for
    one only your own process can write; anything reachable by another user
    or arriving over a network is not that, and should use read_json.
    """

    try:
        content = read_file(path, binary=True, lock=lock)
    except FileNotFoundError:
        return {} if default is _NOT_SET else default

    # bool is an int subclass, so `safe=True` would otherwise compare equal
    # to BLOCKLIST (1) rather than meaning "as safe as it gets".
    if isinstance(safe, bool):
        safe = PickleSafety.STRICT if safe else PickleSafety.NONE

    if safe <= PickleSafety.NONE:
        return pickle.loads(content, **kw)

    return _RestrictedUnpickler(
        io.BytesIO(content), 
        safe, 
        _SAFE_PICKLE_CLASSES | frozenset((cls.__module__, cls.__qualname__) for cls in iter_flat_cont(allow_classes)), 
        to_frozenset(iter_flat_cont(allow_modules)), 
        **kw
    ).load()

def write_pickle(
    path: PathLike, 
    data: Any, 
    lock: Optional[LockProtocol] = None,
    fsync: bool = True,
    **kw,
    ) -> None:

    """Pickle `data` into the file at `path`, replacing it atomically.

    The bytes go through write_file, so the destination is only ever
    swapped in once fully written and fsynced -- an interrupted call leaves
    the previous file intact rather than a half-written one that would fail
    to unpickle.

    `protocol` picks pickle's wire format, and defaults to
    pickle.HIGHEST_PROTOCOL -- the newest one the running interpreter can
    produce (5 since 3.8: out-of-band buffers, so a large buffer-protocol
    object is written without an intermediate copy). pickle's own default,
    DEFAULT_PROTOCOL, is deliberately a notch older (4 on 3.10) to stay
    readable by earlier Pythons.

    Higher is smaller and faster, but a file is only readable by a Python
    whose HIGHEST_PROTOCOL is at least as high -- an older one raises
    ValueError("unsupported pickle protocol"). Pass an explicit `protocol`
    when that matters; the format is forward-compatible, so a newer Python
    reads an older protocol without any flag.

    `data` must not be mutated by another thread while this runs. pickling
    walks the object graph, and a dict that changes size mid-walk raises
    RuntimeError while a list that does silently records a mix of before
    and after -- see the note on write_json, which describes the same
    hazard in full.

    Serialising to bytes first and writing those, rather than pickling
    straight into the file, is deliberate: pickle.dump() writes through a
    Python file object, and every write is a point where another thread can
    run and mutate the structure still being walked. dumps() stays inside
    the C pickler for the whole traversal, which makes the snapshot
    effectively atomic against other threads. It costs ~17% on a large
    object and holds the blob in memory -- paid to keep the default
    correct. Use `atomic_write` with `pickle.dump` directly if you own the
    data outright and want the streaming behaviour back.
    """

    kw.setdefault("protocol", pickle.HIGHEST_PROTOCOL)

    content = pickle.dumps(data, **kw)
    del data
    write_file(path, content, lock=lock, fsync=fsync)




@_optional_import(("jsonref", "jsonref"))
def load_ref_json(
    path: PathLike, 
    default: _T = cast(dict, _NOT_SET), 
    lock: Optional[LockProtocol] = None, **kw
    ) -> Union[JsonValue, _T]:

    """Load the JSON file at `path` and resolve every `$ref` inside it.

    `base_uri` defaults to the file's own location (as a `file://` URI) so
    relative `$ref` targets (e.g. "./schemas/address.json") resolve against
    the file's directory -- without it, jsonref has no directory to resolve
    a relative ref against and raises `JsonRefError` on the first one.
    """

    path = resolve_path(path)

    kw.setdefault("proxies", False)
    kw.setdefault("lazy_load", False)
    kw.setdefault("base_uri", path.as_uri())

    try:
        data = jsonref.loads(read_file(path, encoding="utf-8", lock=lock), **kw)
    except FileNotFoundError:
        data = {} if default is _NOT_SET else default

    return data
    


__all__ = (
    "ensure_path", 
    "ensure_dir", 
    "resolve_path", 
    "remove_file",
    "remove_folder",
    "remove_path", 
    "load_json",
    "save_json",
    "read_json",
    "write_json",
    "load_ref_json",
    "read_pickle",
    "write_pickle",
    "write_file",
    "read_file",
    "truncate_file",
    "atomic_write",
    "remove_files", 
    "remove_folders",
    "remove_paths", 

)