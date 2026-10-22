"""The vocabulary: every closed set of values this package names.

Imports nothing from the package, so it can be read first and alone. If a
value is one of a fixed few -- a verdict, a policy, an exit code, a kind of
contract -- its definition is here and nowhere else, which is what keeps a
typo in one module from inventing a state no other module handles.

All of these are real enums, and the string ones serialise as their values:
they end up in the lock file and the JSON report, where a reader should see
`"flaky"` rather than `"State.FLAKY"`. The relationships *between* members --
which states are fatal, which exit code is worse -- are module-level
constants below each enum rather than attributes on it, because any plain
assignment inside an enum body would become another member.
"""

from __future__ import annotations as _annotations

import sys
from enum import IntEnum
from typing import Final

if sys.version_info >= (3, 11):                   # pragma: no cover
    from enum import StrEnum
else:                                             # pragma: no cover
    from enum import Enum

    class StrEnum(str, Enum):
        """`enum.StrEnum` for 3.10, which `devtools/` still has to run on.

        The two assignments are what the real one does, and they are the
        whole point: without them a member formats as `State.OK` on some
        versions and `ok` on others, so a report and a lock file would
        disagree about what a state is called depending on the interpreter.
        """

        def _generate_next_value_(name: str, *_: object) -> str:
            return name.lower()

        __str__ = str.__str__
        __format__ = str.__format__


# ============================== what a check concluded ==============================

class State(StrEnum):
    """What a single check concluded about one source.

    The distinction that matters is between a source that **died** and one
    that merely could not be **reached**. A 404 means someone removed the
    resource and a developer has to delete it from the tool, since every
    source has bespoke handling there. A timeout means the network blinked.
    Treating the second as the first would hand you a report asking for
    surgery because the Wi-Fi dropped.
    """

    NEW = "new"
    OK = "ok"
    CHANGED = "changed"
    FLAKY = "flaky"
    CONTRACT_BROKEN = "contract_broken"
    GONE = "gone"

    @property
    def is_fatal(self) -> bool:
        """Dead or reshaped: needs a human, not a retry."""
        return self in FATAL_STATES

    @property
    def is_transient(self) -> bool:
        """Stops a run but accuses nobody; `--allow-flaky` passes it."""
        return self in TRANSIENT_STATES

    @property
    def is_clear(self) -> bool:
        """The source answered and is still what it claims to be."""
        return self in CLEAR_STATES

    @property
    def rank(self) -> int:
        """Position in `STATE_ORDER`, for sorting a report worst first."""
        return STATE_ORDER.index(self)


#: Worst first, so a report puts the thing needing action at the top.
STATE_ORDER: Final[tuple[State, ...]] = (
    State.CONTRACT_BROKEN, State.GONE, State.FLAKY,
    State.CHANGED, State.NEW, State.OK)

FATAL_STATES: Final[frozenset[State]] = frozenset(
    {State.CONTRACT_BROKEN, State.GONE})
TRANSIENT_STATES: Final[frozenset[State]] = frozenset({State.FLAKY})
CLEAR_STATES: Final[frozenset[State]] = frozenset(
    {State.NEW, State.OK, State.CHANGED})


# ============================== what the janitor may do ==============================

class Policy(StrEnum):
    """What the janitor does to a cache entry whose source changed.

    The janitor only ever deletes a file or renames it aside. It never reads
    or rewrites one, so it needs no knowledge of any format -- which is the
    whole reason a single generic janitor can serve every tool. A cache that
    must accumulate rather than be refetched is renamed aside and merged by
    the tool that wrote it, because that code already knows the record
    identity and the tie-break.
    """

    #: Drop it; the next build refetches.
    DELETE = "delete"
    #: Rename it aside for the tool to merge on its next harvest.
    MERGE = "merge"
    #: Never remove automatically -- too expensive to rebuild.
    KEEP = "keep"
    #: Say so, touch nothing.
    WARN = "warn"


class Verb(StrEnum):
    """What the janitor reports having done, or what it would do."""

    DELETED = "deleted"
    RENAMED = "renamed"
    KEPT = "kept"
    WARNED = "warned"
    ORPHAN = "orphan"
    SCRATCH = "scratch"

    @property
    def removes(self) -> bool:
        """Whether the cache lost the file, which is what a run records."""
        return self in REMOVING_VERBS


REMOVING_VERBS: Final[frozenset[Verb]] = frozenset(
    {Verb.DELETED, Verb.RENAMED, Verb.SCRATCH})


# ============================== how a body is judged ==============================

class ContractKind(StrEnum):
    """How a source's body is checked for still being what it claims.

    Adding one means adding a member here and a method named after it on
    `ContractCheck`; a test holds the two lists together, so a kind that can
    be declared but not run cannot exist.
    """

    CSV = "csv"
    JSON_LIST = "json_list"
    JSON_OBJECT = "json_object"
    TEXT = "text"
    GIT_REFS = "git_refs"


class FingerprintKind(StrEnum):
    """How a body is reduced to the one value worth comparing between runs."""

    BYTES_LEN = "bytes_len"
    CSV_ROWS = "csv_rows"
    JSON_LEN = "json_len"
    REGEX_COUNT = "regex_count"
    REGEX_MAX_INT = "regex_max_int"
    GIT_HEAD = "git_head"

    @property
    def needs_pattern(self) -> bool:
        """Whether a declaration of this kind is incomplete without one."""
        return self in PATTERN_KINDS


PATTERN_KINDS: Final[frozenset[FingerprintKind]] = frozenset(
    {FingerprintKind.REGEX_COUNT, FingerprintKind.REGEX_MAX_INT})


# ============================== the run's own network ==============================

class Health(StrEnum):
    """Whether a run's failures say more about us than about the sources.

    Eighteen sources do not die in the same minute. When most of a run fails
    to connect, the honest report names the runner's network and escalates
    nothing -- otherwise one bad morning marks every source as suspect and
    the dashboard stops being read.

    Which of the two a run is, is `Checker.network`'s judgement: deciding it
    means reading every verdict, and this module only names the answer.
    """

    OK = "ok"
    DEGRADED = "degraded"


# ============================== what the caller learns ==============================

class Exit(IntEnum):
    """The exit code, which is the whole verdict a scheduler reads.

    Distinct codes rather than a bare failure, because the outcomes call for
    different responses: nothing, a rebuild, a retry, or a developer.
    """

    OK = 0
    #: A source is gone, reshaped, or has failed every run for long enough to
    #: be believed. Needs a human.
    DEAD = 1
    #: Sources are healthy but something moved; a rebuild is worthwhile.
    CHANGED = 2
    #: Could not be reached this once. Not an accusation; retry, or
    #: --allow-flaky, which is what a scheduled run passes.
    UNREACHABLE = 3
    #: A declaration file itself is malformed.
    REGISTRY = 4

    @classmethod
    def worse(cls, a: int, b: int) -> int:
        """The more serious of two codes.

        `--all` has to report the worst outcome across the tools it ran, not
        the first non-zero one: taking the first would answer "unreachable"
        for a run in which another tool's source is dead, and the caller
        would retry instead of fetching a developer. An unrecognised code
        outranks every known one, because nothing here produced it.
        """
        rank = {code: index for index, code in enumerate(EXIT_ORDER)}
        return a if rank.get(a, 0) <= rank.get(b, 0) else b


#: Worst first.
EXIT_ORDER: Final[tuple[Exit, ...]] = (
    Exit.REGISTRY, Exit.DEAD, Exit.UNREACHABLE, Exit.CHANGED, Exit.OK)
