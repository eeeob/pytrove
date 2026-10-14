"""The types: what a tool declares, and what a check concluded.

Two groups, in that order. **The declarations** are parsed out of a tool's
TOML files and are nothing but what the tool says about itself -- no
inference, no tool-specific knowledge, which is what lets one checker serve
every tool under `tools/`. **The results** are what a run produced.

Data and the arithmetic over that data, and no behaviour beyond it: nothing
here reaches the network, the disk or a parser. The properties are the ones
that would otherwise be rewritten at three call sites -- "is this fatal",
"may this run proceed", "which URL does the checker actually request".
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, ClassVar

from .enums import (ContractKind, Exit, FingerprintKind, Health, Policy,
                    State, Verb)

# ============================== how a body is judged ==============================

@dataclass(frozen=True, slots=True)
class Contract:
    """What a source's body must still look like to be considered alive.

    This is what catches the failure mode no status code reveals: a feed that
    answers 200 with a reshaped payload, which a build would happily consume
    and turn into silently wrong data.
    """

    kind: ContractKind
    encoding: str = "utf-8"

    #: kind = csv
    must_have_columns: tuple[str, ...] = ()
    min_rows: int = 0

    #: kind = json_list / json_object
    min_items: int = 0
    item_keys: tuple[str, ...] = ()
    object_keys: tuple[str, ...] = ()

    #: kind = text -- and usable alongside any other kind.
    must_contain: tuple[str, ...] = ()
    must_match: str = ""
    min_matches: int = 0


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

    kind: FingerprintKind
    pattern: str = ""


# ============================== the declarations ==============================

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
    on_change: Policy = Policy.DELETE

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
    def is_cached(self) -> bool:
        return bool(self.url and self.cache)

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
    on_change: Policy = Policy.DELETE

    #: Rebuild once the file itself is older than this, whatever upstream did.
    max_age_days: int = 0
    #: For `merge` only: drop records not seen in this many days.
    record_max_age_days: int = 0

    cost: str = ""
    consumed_by: str = ""
    notes: str = ""


@dataclass(frozen=True, slots=True)
class Citation:
    """A rule this tool ported out of somebody else's source file.

    Some of what a generator emits is not data it collected but a rule it
    reimplemented: lib_base decides what a desktop model string looks like,
    Chromium freezes its own platform tokens, Telegram Android concatenates
    two Build fields with no separator. Those files are read once by a human
    and then quoted in a comment, and a comment cannot notice that the rule
    moved -- so the port goes on producing strings the client would no longer
    produce, and nothing in a build fails.

    So a citation declares the exact lines the port rests on, and the checker
    asks upstream whether they are still there. `anchors` are substrings, not
    line numbers, because line numbers drift on their own: the Android model
    line was cited at 224 and is now at 228, having not changed at all.

    It is not a `[[source]]`. Nothing is fetched into the cache, nothing is
    generated from the body, and a fingerprint of a live source file would
    report a change every week that nobody can act on. The one question worth
    asking is whether the quoted lines survive, and the answer is yes or no.
    """

    id: str
    url: str
    #: Exact substrings the port depends on. All must be present.
    anchors: tuple[str, ...] = ()
    #: Where the rule was reimplemented, named precisely enough that whoever
    #: reads the failure knows which code to re-verify against the file.
    ported_to: str = ""
    #: What the port would get wrong if the rule moved and nobody noticed.
    on_drift: str = ""
    notes: str = ""

    def as_source(self) -> Source:
        """The citation as something the checker already knows how to probe.

        A citation is structurally a probe-only source with a text contract
        and no fingerprint, so it needs no second code path: the contract
        machinery already turns "a required string is missing" into a stated,
        fatal failure, and that is exactly the verdict a moved rule deserves.
        """

        return Source(
            id=self.id,
            probe_url=self.url,
            contract=Contract(kind=ContractKind.TEXT, must_contain=self.anchors),
            consumed_by=self.ported_to,
            on_removal=self.on_drift,
            notes=self.notes,
        )


@dataclass(frozen=True, slots=True)
class Watch:
    """A value this tool decided by hand, and the upstream that informs it.

    Not everything a generator needs can be fetched. Nothing publishes the
    share of machines running Windows 11, so the weights are a judgement; the
    Android API level table is typed out from a documentation page; the glibc
    versions in the Linux pool were read off a package index. Each of those is
    a decision, and a decision goes stale quietly -- the build keeps working,
    the numbers just stop describing the world.

    So a watch records the decision together with the one number upstream can
    still be asked for: `value` is what the tool believes, `fingerprint` is
    how to read the current answer, and a difference is reported every run
    until somebody revisits it. The baseline lives in the declaration, a
    tracked file a human edits, rather than in the lock -- which is why a
    moved value keeps being mentioned instead of being re-recorded.

    A watch never gates a build. The generator does not read these URLs at
    all, so a page that moved is news, not an obstacle.
    """

    id: str
    url: str
    #: What the decision in the code currently reflects.
    value: Any
    #: How to read the comparable number out of the body.
    fingerprint: Fingerprint
    #: Where the decision lives, named precisely enough to go and change it.
    used_by: str
    #: Why this is hand-kept rather than fetched, and what to do when it moves.
    decision: str = ""
    notes: str = ""

    def as_source(self) -> Source:
        """The watch as something `Prober` already knows how to request.

        A probe URL and a fingerprint, with no contract and no cache: the body
        is read for one number and then dropped.
        """

        return Source(id=self.id, probe_url=self.url,
                      fingerprint=self.fingerprint)


@dataclass(frozen=True, slots=True)
class Schedule:
    """One tool's cadence: how often its sources are checked unattended.

    The cadence exists twice and there is no way around it -- GitHub Actions
    cannot compute a trigger, so the workflow has to carry the cron literally
    -- so the declaration is the record and a test holds the two together.
    Nothing is read back from the workflow: a YAML parser is not a dependency
    this package takes on for one string.
    """

    tool: str
    cron: str
    notes: str = ""

    #: A cron line has five fields, and only these three shapes are a cadence
    #: that can be stated in days. `*/3` in the day field is a perfectly good
    #: cron and not one of them, so it is refused at parse time rather than
    #: rounded to something plausible.
    FIELDS: ClassVar[int] = 5
    DAILY: ClassVar[int] = 1
    WEEKLY: ClassVar[int] = 7
    MONTHLY: ClassVar[int] = 30
    ANY: ClassVar[str] = "*"

    @property
    def every_days(self) -> int:
        """Days between two runs, or 0 when the cron does not say.

        Derived rather than declared. A second number in the file would be
        one more thing to drift, and this one has a real reader: the
        escalation rule counts runs, because a run is the only thing it can
        count, and three runs is a different promise at a weekly cadence than
        at a daily one. The report turns one into the other with this.
        """

        parts = self.cron.split()
        if len(parts) != self.FIELDS:
            return 0
        _, _, day, month, weekday = parts
        if month != self.ANY:
            return 0
        if day == self.ANY and weekday == self.ANY:
            return self.DAILY
        if day == self.ANY and weekday.isdigit():
            return self.WEEKLY
        if weekday == self.ANY and day.isdigit():
            return self.MONTHLY
        return 0


@dataclass(frozen=True, slots=True)
class Registry:
    """One tool's whole declaration, as parsed.

    Three kinds of promise, and breaking one costs three different things:

    `sources`     fetched, cached and parsed on every build. A dead or
                  reshaped one stops everything.
    `citations`   read once by a human and reimplemented. A moved rule stops
                  everything too, because the port would otherwise keep
                  emitting strings the client no longer produces.
    `watches`     decided by hand. Never gates anything: the generator does
                  not read those URLs at all.
    """

    tool: str
    tool_dir: Path
    cache_dir: Path
    #: Directories inside the cache that must never survive a run (a half
    #: finished clone, an extraction). The janitor removes them unasked.
    scratch: tuple[str, ...] = ()
    sources: tuple[Source, ...] = ()
    derived: tuple[Derived, ...] = ()
    citations: tuple[Citation, ...] = ()
    watches: tuple[Watch, ...] = ()

    # --- lookups ----------------------------------------------------------

    def source(self, source_id: str) -> Source | None:
        return next((s for s in self.sources if s.id == source_id), None)

    def citation(self, source_id: str) -> Citation | None:
        return next((c for c in self.citations if c.id == source_id), None)

    def watch(self, source_id: str) -> Watch | None:
        return next((w for w in self.watches if w.id == source_id), None)

    # --- derived views ----------------------------------------------------

    @property
    def probes(self) -> tuple[Source, ...]:
        """Everything compared against the lock, in one list.

        Citations come last so a report's table reads sources first, and they
        arrive already shaped as sources: every rule downstream -- network
        health, the failure counter, the exit code -- then applies to a moved
        rule exactly as it does to a moved feed, which is what it deserves.

        Watches are not here. Their baseline is their own declaration rather
        than the lock, so they are compared against a different thing.
        """

        return self.sources + tuple(c.as_source() for c in self.citations)

    @property
    def declared_cache_files(self) -> frozenset[str]:
        """Every cache name the registry accounts for.

        The janitor compares this against what is on disk: a file there that
        nothing declares is either a leftover from a renamed key or -- the one
        that matters -- a source somebody added to the tool and forgot to
        register, which would then never be checked at all. Citations and
        watches contribute nothing; they are never fetched into the cache.
        """

        return frozenset(
            {s.cache for s in self.sources if s.cache}
            | {d.cache for d in self.derived if d.cache})


# ============================== the results ==============================

@dataclass(frozen=True, slots=True)
class Verdict:
    """What one source's check concluded, and everything a report needs."""

    source_id: str
    state: State
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
        return self.state.is_fatal

    @property
    def is_transient(self) -> bool:
        return self.state.is_transient

    @property
    def is_clear(self) -> bool:
        return self.state.is_clear


@dataclass(frozen=True, slots=True)
class Report:
    """Everything one check run concluded."""

    tool: str
    verdicts: tuple[Verdict, ...]
    network: Health
    first_run: bool
    #: Ids that are watched values rather than things the tool reads. A watch
    #: never gates a build -- the generator never requests these URLs -- so a
    #: page that moved is news and not an obstacle. It is still reported, and
    #: it still escalates if it stays broken.
    watched: frozenset[str] = frozenset()

    #: Consecutive failing runs before a source is called dead rather than
    #: unlucky. Weekly scheduling makes this three weeks, long enough that no
    #: ordinary outage reaches it and short enough to still matter.
    ESCALATE_AFTER: ClassVar[int] = 3

    # --- what happened ----------------------------------------------------

    @property
    def gating(self) -> tuple[Verdict, ...]:
        """The verdicts that can stop a build: everything but the watches."""

        return tuple(v for v in self.verdicts
                     if v.source_id not in self.watched)

    @property
    def fatal(self) -> tuple[Verdict, ...]:
        """Sources that died. These need a developer, not a retry."""

        return tuple(v for v in self.gating if v.is_fatal)

    @property
    def transient(self) -> tuple[Verdict, ...]:
        return tuple(v for v in self.gating if v.is_transient)

    @property
    def changed(self) -> tuple[Verdict, ...]:
        return tuple(v for v in self.verdicts if v.state is State.CHANGED)

    @property
    def escalated(self) -> tuple[Verdict, ...]:
        """Sources that have failed every run for long enough to be believed.

        A single failure is weather. The counter lives in the tracked lock so
        it survives a fresh CI runner, and this is the one place it is read.
        """

        return tuple(v for v in self.verdicts
                     if v.consecutive >= self.ESCALATE_AFTER)

    def sorted_verdicts(self) -> list[Verdict]:
        """Worst first, so what needs action is at the top of the report."""

        return sorted(self.verdicts,
                      key=lambda v: (v.state.rank, v.source_id))

    # --- the gate ---------------------------------------------------------

    def may_proceed(self, *, allow_flaky: bool = False) -> bool:
        """Whether the run's next step may start.

        A dead source always stops it. An unreachable one stops it too, by
        default -- building past a source you could not reach risks a
        half-complete catalog -- but `--allow-flaky` passes it, because the
        cache usually covers the gap entirely and a dropped connection is not
        a reason to be unable to build.
        """

        if self.fatal:
            return False
        return allow_flaky or not self.transient

    def exit_code(self, *, allow_flaky: bool = False) -> Exit:
        """The one thing a scheduler reads.

        An escalated source is DEAD and `--allow-flaky` does not waive it.
        That is the whole point of counting consecutive runs: the waiver
        covers a dropped connection, not three weeks of one, and until
        something acted on the count the rule was a sentence in a report that
        changed no outcome.
        """

        if self.fatal or self.escalated:
            return Exit.DEAD
        if self.transient and not allow_flaky:
            return Exit.UNREACHABLE
        if self.changed:
            return Exit.CHANGED
        return Exit.OK


@dataclass(frozen=True, slots=True)
class Action:
    """One thing the janitor did, or would do."""

    verb: Verb
    cache: str
    reason: str
    target: str = ""

    def __str__(self) -> str:
        arrow = f" -> {self.target}" if self.target else ""
        return f"{self.verb:<8} {self.cache}{arrow}  ({self.reason})"
