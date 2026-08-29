"""Types belonging to archive_tools.

`ArchiveLimits` lives here rather than beside the extractor because of which side
of the line it falls on: it is an argument callers build and hand over, not
machinery they call. It is named in extract_archive's signature, so it is
part of the interface, and an interface should not have to be imported out
of a module whose name starts with an underscore.

The one dependency reaching out of this package is `..enums`, which holds
the four policies as public enums. It imports nothing internal at all, so
the foundation layer stays acyclic.
"""


from pathlib import Path
from typing import Callable, NamedTuple, Optional
from ..enums import ArchiveDuplicatePolicy, ArchiveLinkPolicy, ArchiveOverwritePolicy


class ArchiveLimits(NamedTuple):
    """What an extraction may write, and what it may write it as.

    Passed to archive_tools.extract_archive as `limits`. Immutable, so one
    instance can be shared by any number of calls, and comparable and
    hashable by value like any other tuple.

    The six ceilings are None by default, meaning no ceiling. A library
    that started refusing archives it used to accept would break working
    code, and there is no honest number anyway: 500 MB is paranoid for a
    backup and reckless for an upload. extract_archive documents the risk
    and the caller picks.

    max_files counts every member written -- files, directories and links
    alike -- because what it is there to bound is how many filesystem
    entries an archive may create, and a million empty directories costs
    what a million empty files costs.

    max_dir_entries is the same count taken one directory at a time, and it
    is the breadth of the tree where max_depth is the height. An archive
    can stay well inside max_files and still put every one of those members
    in a single directory, which is its own kind of damage: a listing goes
    quadratic on the filesystems that do not index directories, and the
    tools people use to look at the result stop responding long before the
    disk fills. Counted per directory, including the directories a member's
    own path implies but the archive never listed, so "a/b/c.txt" is one
    entry in "a/b" whether or not "a/b/" was a member of its own.

    dir_check is the same question asked in the caller's own words rather
    than in a number, and it is the only one that gets to look at what was
    actually extracted. It is handed one directory as a Path, on disk, with
    its contents already in it, and may:

        return None, or anything true      the directory is fine
        return False, or anything falsey   drop it, and its whole subtree
        raise                              stop the extraction, with that
                                           exception, unchanged

    So it can ask what nothing else here can:

        def sane(d):
            if any(p.suffix == ".exe" for p in d.iterdir()):
                raise ValueError(f"{d.name!r} carries an executable")
            return sum(p.stat().st_size for p in d.iterdir()) < (1 << 30)

        ArchiveLimits(dir_check=sane)
        ArchiveLimits(dir_check=lambda d: d.name != ".git")

    It runs once every member has been written, outermost directory first,
    once per directory -- every directory the extraction produced, whether
    the archive listed it as a member of its own or only implied it through
    a member's path. A refused directory is not descended into, so a branch
    cut near the root costs one call however deep it went.

    Judge the directory by its own name or its contents, not by where it
    sits: an extraction with a dir_check always writes into a staging
    directory first, so `d` is an absolute path under a temporary sibling
    of `dest` rather than under `dest` itself. `d.name`, `d.iterdir()` and
    `d.stat()` all mean what they look like; `str(d).startswith(str(dest))`
    does not.

    That staging is not optional and is what keeps a refusal safe. Dropping
    a directory means removing it after it was written, and doing that in
    `dest` would delete whatever was already living there under the same
    name -- which nobody asked for by passing a check. The staging tree
    holds this archive and nothing else, and `dest` is only written once
    every check has passed.

    The price is that a refused subtree is extracted, counted against the
    ceilings, and then removed, where the name-only check this replaced
    could refuse a branch before a byte of it was written. That is the
    trade for being able to see inside. `exclude` still prunes before
    anything is read and is the tool to reach for when the question is
    which files you want; this one is for whether what arrived is
    acceptable at all.

    max_ratio is the zip bomb check: a member declaring far more bytes than
    it stores is the whole of that attack. 42.zip fits in 42 KB and claims
    4.5 PB, a ratio near 10**11. Legitimate ratios above 1000 do occur (a
    large file of zeros), so the number is a policy, not a fact.

    The four policies are not like the ceilings: each defaults to the safe
    answer rather than to none. Each takes its own enum -- ArchiveLinkPolicy,
    ArchiveOverwritePolicy and ArchiveDuplicatePolicy, all in pytrove.enums --
    or the plain string spelling those enums carry, since they are str enums
    and the two are interchangeable:

        ArchiveLimits(symlinks=ArchiveLinkPolicy.ALLOW, duplicates="error")
        ArchiveLimits(symlinks="allow", overwrite="skip")

    None of them says anything about *when* a check happens. There is one
    answer to that and it is not configurable: a member is written as it is
    read, and everything here is settled on the way past. What is left on
    disk when a check refuses one is extract_archive's business, not this
    type's -- see its `atomic` and `cleanup_on_error`.

    Nothing here is checked before the extraction begins, because nothing
    here needs to be. A ceiling that is not a number fails at the first
    comparison it reaches and a dir_check that is not callable fails at the
    first call -- both at once, and both naming themselves. A misspelled
    policy is the quiet one, and the reason it can be left alone is that no
    comparison matches it, so it falls to the conservative side of its own
    setting: "allowed" behaves as skip, "nope" as skip, "validate_frist" as
    streaming. A typo can cost you an unwritten member. It cannot buy an
    archive a permission you did not grant.

    What is *not* here is any say over a member's name. A name that is
    absolute, or that climbs out with "..", is refused and logged whatever
    the settings. Writing where such a name asks to go is the vulnerability
    the extractor exists to prevent, and an option is only worth having
    where both answers are defensible.
    """

    max_files: Optional[int] = None
    max_total_size: Optional[int] = None
    max_file_size: Optional[int] = None
    max_ratio: Optional[float] = None
    max_depth: Optional[int] = None
    max_dir_entries: Optional[int] = None
    dir_check: Optional[Callable[[Path], Optional[bool]]] = None

    symlinks: ArchiveLinkPolicy = ArchiveLinkPolicy.ERROR
    hardlinks: ArchiveLinkPolicy = ArchiveLinkPolicy.ERROR
    overwrite: ArchiveOverwritePolicy = ArchiveOverwritePolicy.OVERWRITE
    duplicates: ArchiveDuplicatePolicy = ArchiveDuplicatePolicy.SKIP

    @classmethod
    def permissive(cls, **kw) -> "ArchiveLimits":
        """Links restored, for an archive whose maker you are.

        Only what can be made safe is relaxed: a link is still refused if
        it points outside the destination, because a link that escapes is
        not one the archive was entitled to ask for. The ceilings are
        untouched -- pass them if you want them.
        """

        return cls(symlinks=ArchiveLinkPolicy.ALLOW, hardlinks=ArchiveLinkPolicy.ALLOW, **kw)


__all__ = (
    "ArchiveLimits",
)
