"""The types a tool's `sources/sources.toml` is parsed into.

Imports nothing from this package, so it can be read first. Every field here
is something a tool declares about itself; nothing is inferred and nothing is
tool-specific, which is what lets one checker serve every tool under tools/.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, ClassVar

# ============================== the states ==============================

class State:
    """What a single check concluded about one source.

    Written as plain strings rather than an enum because `tools/` has to run
    on Python 3.10, where `StrEnum` does not exist, and these values are
    serialised into the lock file and the JSON report as they are.

    The distinction that matters is between a source that **died** and one
    that merely could not be **reached**. A 404 means someone removed the
    resource and a developer has to delete it from the tool's source, since
    every source has bespoke handling there. A timeout means the network
    blinked. Treating the second as the first would hand you a report asking
    for surgery because the Wi-Fi dropped.
    """

    NEW: ClassVar[str] = "new"
    OK: ClassVar[str] = "ok"
    CHANGED: ClassVar[str] = "changed"
    FLAKY: ClassVar[str] = "flaky"
    CONTRACT_BROKEN: ClassVar[str] = "contract_broken"
    GONE: ClassVar[str] = "gone"

    #: States that mean the source is dead and needs a human to remove it.
    FATAL: ClassVar[frozenset[str]] = frozenset({CONTRACT_BROKEN, GONE})
    #: States that stop the run but accuse nobody; `--allow-flaky` passes them.
    TRANSIENT: ClassVar[frozenset[str]] = frozenset({FLAKY})
    #: States the run may proceed through.
    CLEAR: ClassVar[frozenset[str]] = frozenset({NEW, OK, CHANGED})

    #: Worst-first, for sorting a report so the thing needing action is on top.
    ORDER: ClassVar[tuple[str, ...]] = (
        CONTRACT_BROKEN, GONE, FLAKY, CHANGED, NEW, OK)

    @classmethod
    def rank(cls, state: str) -> int:
        return cls.ORDER.index(state) if state in cls.ORDER else len(cls.ORDER)


class Policy:
    """What the janitor does to a cache entry whose source changed.

    The janitor only ever deletes a file or renames it aside. It never reads
    or rewrites one, so it needs no knowledge of any format -- which is the
    whole reason a single generic janitor can serve every tool. A cache that
    must accumulate rather than be refetched is renamed to `<name>.prev<ext>`
    and merged by the tool that wrote it, because that code already knows the
    record identity and the tie-break.
    """

    DELETE: ClassVar[str] = "delete"
    MERGE: ClassVar[str] = "merge"
    KEEP: ClassVar[str] = "keep"
    WARN: ClassVar[str] = "warn"

    ALL: ClassVar[frozenset[str]] = frozenset({DELETE, MERGE, KEEP, WARN})

    #: Suffix inserted before the extension when a `merge` entry is set aside.
    PREV: ClassVar[str] = ".prev"


# ============================ the declarations ============================

@dataclass(frozen=True, slots=True)
class Contract:
    """What a source's body must still look like to be considered alive.

    This is what catches the failure mode no status code reveals: a feed that
    answers 200 with a reshaped payload, which a build would happily consume
    and turn into silently wrong data.
    """

    kind: str
    encoding: str = "utf-8"

    #: kind = "csv"
    must_have_columns: tuple[str, ...] = ()
    min_rows: int = 0

    #: kind = "json_list" / "json_object"
    min_items: int = 0
    item_keys: tuple[str, ...] = ()
    object_keys: tuple[str, ...] = ()

    #: kind = "text" -- and usable alongside any other kind.
    must_contain: tuple[str, ...] = ()
    must_match: str = ""
    min_matches: int = 0

    KINDS: ClassVar[frozenset[str]] = frozenset(
        {"csv", "json_list", "json_object", "text", "git_refs"})




@dataclass(frozen=True, slots=True)
class Fingerprint:
    """How to reduce a body to one value worth watching.

    A hash changes on every trivial edit upstream, which makes it useless as
    a signal: it says "something moved" and never what. A semantic value --
    the newest Chrome major, the Play catalog's row count, the DMI repo's HEAD
    -- says what moved and by how much, and reads as a sentence on the weekly
    dashboard. The hash is recorded too, as the fallback for bodies that have
    no natural scalar.
    """

    kind: str
    pattern: str = ""

    KINDS: ClassVar[frozenset[str]] = frozenset(
        {"bytes_len", "csv_rows", "json_len", "regex_count", "regex_max_int",
         "git_head"})


@dataclass(frozen=True, slots=True)
class Source:
    """One upstream the tool depends on.

    Two shapes, distinguished by which URL field is set:

    `url`         the whole body is fetched and cached under `cache`. The
                  checker probes it conditionally, runs the contract over the
                  body and fingerprints it.
    `probe_url`   there is no single cacheable URL -- the tool queries the
                  endpoint once per device, or clones it over git. The checker
                  hits one representative request to prove the endpoint is
                  alive and still shaped as expected. Its cache, if any, is
                  declared as a `[[derived]]` entry instead.
    """

    id: str
    url: str = ""
    probe_url: str = ""
    cache: str = ""
    on_change: str = Policy.DELETE

    contract: Contract | None = None
    fingerprint: Fingerprint | None = None

    #: Where in the tool this source is read, named precisely enough that a
    #: developer told to remove it knows every place to look.
    consumed_by: str = ""
    #: What the tool loses if this source is deleted. The failure report
    #: prints it, because a dead source means a code change, not a retry.
    on_removal: str = ""
    notes: str = ""

    @property
    def target(self) -> str:
        """The URL the checker actually requests."""

        return self.url or self.probe_url

    @property
    def digest(self) -> str:
        """A short, stable hash of how this source is judged.

        Covers the contract and the fingerprint together, and is recorded in
        the lock, because a conditional request answered with 304 carries no
        body: there is nothing to run a contract over and nothing to
        fingerprint. That is sound only while the declaration is the same one
        the stored verdict was reached under. Without this, tightening a
        contract or fixing a wrong fingerprint pattern would never take
        effect -- the lock would keep serving the old answer forever. A
        differing digest makes the next request unconditional.
        """

        parts = "|".join(
            str(getattr(block, f.name))
            for block in (self.contract, self.fingerprint) if block is not None
            for f in fields(block)
        )
        return hashlib.sha256(parts.encode()).hexdigest()[:12] if parts else ""

    @property
    def is_cached(self) -> bool:
        return bool(self.url and self.cache)


@dataclass(frozen=True, slots=True)
class Derived:
    """A cache file the tool produced itself, rather than downloaded.

    These have no URL and therefore no fingerprint of their own: a file built
    from 39 separate requests, or from 5,700, cannot be conditionally
    revalidated. So they go stale by *dependency* -- when a source they were
    built from changes -- or by age. `cost` is recorded because it is the
    argument for the policy: a cache that takes 5,700 requests to rebuild is
    `keep`, not `delete`, or any unrelated change upstream would trigger it.
    """

    id: str
    cache: str
    derives_from: tuple[str, ...] = ()
    on_change: str = Policy.DELETE

    #: Rebuild once the file itself is older than this, whatever upstream did.
    max_age_days: int = 0
    #: For `merge` only: drop records not seen in this many days.
    record_max_age_days: int = 0

    cost: str = ""
    consumed_by: str = ""
    notes: str = ""


@dataclass(frozen=True, slots=True)
class Registry:
    """One tool's whole declaration, as parsed."""

    tool: str
    tool_dir: Path
    cache_dir: Path
    #: Directories inside the cache that must never survive a run (a half
    #: finished clone, an extraction). The janitor removes them unasked.
    scratch: tuple[str, ...] = ()
    sources: tuple[Source, ...] = ()
    derived: tuple[Derived, ...] = ()
    #: Sections this checker does not implement yet, kept so a registry written
    #: for a later phase still loads: `watch` lands with config/, `citation`
    #: with ported/.
    deferred: dict[str, int] = field(default_factory=dict)

    def source(self, source_id: str) -> Source | None:
        return next((s for s in self.sources if s.id == source_id), None)

    @property
    def declared_cache_files(self) -> frozenset[str]:
        """Every cache name the registry accounts for.

        The janitor compares this against what is on disk: a file in `.cache`
        that nothing declares is either a leftover from a renamed key or a
        source somebody added to the code and forgot to register, and both are
        worth saying out loud.
        """

        return frozenset(
            {s.cache for s in self.sources if s.cache}
            | {d.cache for d in self.derived if d.cache})


# ============================== the results ==============================

@dataclass(frozen=True, slots=True)
class Verdict:
    """What one source's check concluded, and everything the report needs."""

    source_id: str
    state: str
    #: Fingerprint values, previous and current, for "156 -> 157" in a report.
    was: Any = None
    now: Any = None
    http_status: int | None = None
    error: str = ""
    #: How many consecutive runs have now failed on this source.
    consecutive: int = 0
    attempts: int = 1
    elapsed_ms: int = 0
    #: The body, kept only long enough for the janitor and the lock writer.
    body: bytes | None = field(default=None, compare=False, repr=False)
    sha256: str = ""
    bytes_len: int = 0
    etag: str = ""
    last_modified: str = ""
    contract_errors: tuple[str, ...] = ()
    #: The digest of the declaration -- contract and fingerprint -- this
    #: verdict was produced under, so the lock can notice one that changed.
    declaration: str = ""

    @property
    def is_fatal(self) -> bool:
        return self.state in State.FATAL

    @property
    def is_transient(self) -> bool:
        return self.state in State.TRANSIENT

    @property
    def is_clear(self) -> bool:
        return self.state in State.CLEAR
