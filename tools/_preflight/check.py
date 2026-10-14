"""Deciding what each source's answer means, against what the lock remembers.

`probe` reaches a source, `contract` says whether it is still valid and
`fingerprint` says what it is now. This module is the one that compares, and
therefore the only one that can conclude `changed` or `new`.

It never writes anything: the caller owns the order, because the janitor has
to run *before* the lock is rewritten. Overwriting the lock first would erase
the comparison the cleaning is based on, and every later run would see
"unchanged" and leave the cache stale forever -- the exact defect this whole
thing exists to remove.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from .contract import ContractCheck
from .fingerprint import FingerprintValue
from .lock import Lock
from .model import Registry, Source, State, Verdict
from .probe import Health, Prober

# ============================== the result ==============================

@dataclass(frozen=True, slots=True)
class Report:
    """Everything one check run concluded."""

    tool: str
    verdicts: tuple[Verdict, ...]
    network: str
    first_run: bool
    deferred: dict[str, int] = field(default_factory=dict)

    #: Consecutive failing runs before a source is called dead rather than
    #: unlucky. Weekly scheduling makes this three weeks, long enough that no
    #: ordinary outage reaches it and short enough to still matter.
    ESCALATE_AFTER: ClassVar[int] = 3

    # --- the gate ---------------------------------------------------------

    @property
    def fatal(self) -> tuple[Verdict, ...]:
        """Sources that died. These need a developer, not a retry."""

        return tuple(v for v in self.verdicts if v.is_fatal)

    @property
    def transient(self) -> tuple[Verdict, ...]:
        return tuple(v for v in self.verdicts if v.is_transient)

    @property
    def changed(self) -> tuple[Verdict, ...]:
        return tuple(v for v in self.verdicts if v.state == State.CHANGED)

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

    @property
    def escalated(self) -> tuple[Verdict, ...]:
        """Sources that have failed every run for long enough to be believed.

        A single failure is weather. The counter lives in the tracked lock so
        it survives a fresh CI runner, and this is the one place it is read:
        the report says so out loud, and the scheduler reads the same number
        out of the JSON to decide whether a dashboard needs a new comment.
        """

        return tuple(v for v in self.verdicts
                     if v.consecutive >= self.ESCALATE_AFTER)

    def sorted_verdicts(self) -> list[Verdict]:
        """Worst first, so what needs action is at the top of the report."""

        return sorted(self.verdicts,
                      key=lambda v: (State.rank(v.state), v.source_id))


# ============================== the checker ==============================

class Checker:
    """Probes every source in a registry and compares it to the lock."""

    def __init__(self, registry: Registry, lock: Lock,
                 *, prober: Prober | None = None) -> None:
        self.registry = registry
        self.lock = lock
        self.prober = prober or Prober()

    # --- one source -------------------------------------------------------

    def check_one(self, source: Source) -> Verdict:
        digest = source.digest

        # A conditional request is an optimisation that assumes the previous
        # verdict still stands, so it is only safe on three conditions: the
        # declaration is the same one that verdict was reached under, that
        # verdict was a pass, and the validator promises the bytes rather
        # than the meaning. Any of them failing makes a 304 a lie -- a
        # tightened contract or a corrected pattern would never take effect,
        # a recorded failure would disappear on the very next run, and a
        # reshaped feed behind a weak validator would never be read again.
        # The third condition is `Lock.validators`' own; the other two are
        # here, because only the lock entry answers them.
        was = self.lock.entry(source.id)
        trustworthy = (
            (not digest or digest == was.get("declaration", ""))
            and was.get("contract", "ok") == "ok"
        )
        etag, last_modified = (
            self.lock.validators(source.id) if trustworthy else ("", ""))

        verdict = self._replace(
            self.prober.probe(source, etag=etag, last_modified=last_modified),
            declaration=digest)

        if not verdict.is_clear:
            return self._failed(source, verdict)

        # A 304 is the cheapest possible "unchanged": no body came back, so
        # there is nothing to run a contract over and nothing to compare.
        if verdict.body is None:
            return self._replace(verdict, state=State.OK,
                                 was=self.lock.fingerprint(source.id),
                                 now=self.lock.fingerprint(source.id))

        errors = ContractCheck.run(source.contract, verdict.body)
        if errors:
            return self._failed(
                source,
                self._replace(verdict, state=State.CONTRACT_BROKEN,
                              contract_errors=errors,
                              error=errors[0]))

        encoding = source.contract.encoding if source.contract else "utf-8"
        now = FingerprintValue.of(source.fingerprint, verdict.body, encoding=encoding)
        was = self.lock.fingerprint(source.id)

        if self.lock.is_new or not self.lock.entry(source.id):
            state = State.NEW
        elif self._moved(was, now, verdict.sha256, self.lock.sha256(source.id)):
            state = State.CHANGED
        else:
            state = State.OK

        return self._replace(verdict, state=state, was=was, now=now)

    @classmethod
    def _moved(cls, was: Any, now: Any, sha_now: str, sha_was: str) -> bool:
        """Did upstream change?

        The semantic fingerprint decides when there is one, because it is the
        value a human can read. The hash only decides for sources that have
        no natural scalar -- otherwise a reformatted feed with an identical
        newest version would be reported as a change nobody can act on.
        """

        if now is not None or was is not None:
            return was != now
        return bool(sha_was) and sha_was != sha_now

    def _failed(self, source: Source, verdict: Verdict) -> Verdict:
        """Attach the consecutive-failure count a dead/unreachable source carries."""

        return self._replace(
            verdict, consecutive=self.lock.consecutive(source.id) + 1)

    @staticmethod
    def _replace(verdict: Verdict, **changes: Any) -> Verdict:
        from dataclasses import replace
        return replace(verdict, **changes)

    # --- the whole registry -----------------------------------------------

    def run(self) -> Report:
        verdicts = [self.check_one(probe) for probe in self.registry.probes]
        network = Health.assess(verdicts)

        # When the network is the problem, nothing is accused: every flaky
        # verdict keeps its state for the report but its counter is reset, so
        # one bad morning cannot push a healthy source towards "dead".
        if network == Health.DEGRADED:
            verdicts = [
                self._replace(v, consecutive=0) if v.is_transient else v
                for v in verdicts
            ]

        return Report(
            tool=self.registry.tool,
            verdicts=tuple(verdicts),
            network=network,
            first_run=self.lock.is_new,
            deferred=dict(self.registry.deferred),
        )
