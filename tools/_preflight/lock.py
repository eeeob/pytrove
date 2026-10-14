"""The two files that remember what the last check saw.

They are split on one rule: **the tracked file holds only what is worth
seeing change.**

    sources/sources.lock.json     tracked. facts about upstream: fingerprints,
                                  HTTP validators, failure counters. Written
                                  only when its content actually differs, so a
                                  diff means something moved in the world and
                                  `git log -p` on it is the history of that.

    .cache/preflight.state.json   gitignored. run bookkeeping: when the check
                                  last ran, how long it took, what the janitor
                                  removed. None of it belongs in a diff.

Putting `last_checked` in the tracked file was the mistake this split avoids:
a weekly check would then produce a commit every week with nothing learnt,
and the signal would drown within a month.

The failure counter goes the other way -- it has to be in the *tracked* file,
because a CI runner is new every week and would reset an ephemeral one, and
the three-consecutive-runs rule depends on it surviving. It is written only
while non-zero, so its appearance in a diff is the alarm and its
disappearance is the recovery.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from .enums import State
from .models import Registry, Verdict

# ============================== the lock file ==============================

class Lock:
    """`sources/sources.lock.json`: what upstream looked like last time."""

    SCHEMA: ClassVar[int] = 1

    #: Top-level sections. A verdict is routed to one of the two written
    #: ones by what the registry says it is, so a diff stays readable: a line
    #: under `sources` means data moved, a line under `citations` means a rule
    #: somebody ported has moved and the port needs re-reading. `watches`
    #: lands with a later phase and is only carried through.
    SOURCES: ClassVar[str] = "sources"
    CITATIONS: ClassVar[str] = "citations"
    #: A watch keeps no facts here at all -- its baseline is the value
    #: declared in config/config.toml, where a human can edit it -- so this
    #: section holds only the failure counter, and only while it is failing.
    WATCHES: ClassVar[str] = "watches"
    WRITTEN: ClassVar[tuple[str, ...]] = (SOURCES, CITATIONS, WATCHES)

    #: Present on an entry only while it is failing, so an all-clear run
    #: leaves no trace and produces no diff.
    FAILING: ClassVar[str] = "failing"

    #: The prefix of a weak ETag. Only a *strong* validator may shorten a
    #: check: a weak one means "semantically equivalent" (RFC 9110 8.8.3),
    #: and `Last-Modified` is weak by definition at one-second granularity.
    #: Either lets an origin answer 304 for a body that is not the one we
    #: validated -- and a 304 carries no body, so there is nothing to run the
    #: contract over. The contract would then be evaluated once, on the very
    #: first run, and never again, which is the one failure this whole thing
    #: exists to catch. Measured against the eighteen real sources: thirteen
    #: revalidate conditionally, two advertise a weak ETag and one sends only
    #: Last-Modified, so three of them were silently exempt.
    WEAK: ClassVar[str] = "W/"

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = self._read()

    # --- reading ----------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"lock_schema": self.SCHEMA, self.SOURCES: {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"lock_schema": self.SCHEMA, self.SOURCES: {}}
        data.setdefault(self.SOURCES, {})
        return data

    @property
    def is_new(self) -> bool:
        """True on a clean clone, before anything has been recorded.

        The first check must then report every source as `new`, never as
        `changed`: eighteen false alarms on day one teach a maintainer to
        ignore the dashboard, and it never recovers from that.
        """

        return not self.path.is_file()

    def entry(self, source_id: str) -> dict[str, Any]:
        """What was recorded for this id, whichever section it sits in.

        The caller never has to know which kind it asked about: an id belongs
        to exactly one of them, enforced where the registry is parsed.
        """

        for section in self.WRITTEN:
            found = self.data.get(section, {}).get(source_id)
            if found is not None:
                return found
        return {}

    def validators(self, source_id: str) -> tuple[str, str]:
        """(etag, last_modified) worth sending -- or nothing.

        `last_modified` is recorded as a readable upstream fact but is never
        sent back, and a weak ETag is withheld too. A 304 earned either way
        would be a claim about meaning rather than about bytes, and the whole
        point of revalidating is to be able to re-read the shape.
        """

        etag = self.entry(source_id).get("http", {}).get("etag", "")
        return ("", "") if etag.startswith(self.WEAK) else (etag, "")

    def fingerprint(self, source_id: str) -> Any:
        return self.entry(source_id).get("fingerprint")

    def sha256(self, source_id: str) -> str:
        return self.entry(source_id).get("sha256", "")

    def consecutive(self, source_id: str) -> int:
        return int(self.entry(source_id).get(self.FAILING, {}).get("consecutive", 0))

    def failing_since(self, source_id: str) -> str:
        return self.entry(source_id).get(self.FAILING, {}).get("since", "")

    # --- writing ----------------------------------------------------------

    def rebuild(self, registry: Registry, verdicts: list[Verdict],
                today: str | None = None) -> dict[str, Any]:
        """The lock as it should now be, without touching the file.

        An entry is carried forward unchanged when a source could not be
        reached: a timeout must not erase the fingerprint we are comparing
        against, or the next run would call everything `new`.
        """

        today = today or date.today().isoformat()
        previous = {**self.data.get(self.CITATIONS, {}),
                    **self.data.get(self.SOURCES, {})}
        written: dict[str, dict[str, Any]] = {s: {} for s in self.WRITTEN}

        for verdict in verdicts:
            if registry.watch(verdict.source_id) is not None:
                if verdict.consecutive:
                    written[self.WATCHES][verdict.source_id] = {
                        self.FAILING: self._failing(verdict, today)}
                continue

            was = previous.get(verdict.source_id, {})
            carried = {k: v for k, v in was.items() if k != self.FAILING}

            # A changed declaration is itself worth recording, so an
            # `ok` run writes when the digest moved -- once, not every run.
            restated = bool(
                verdict.declaration
                and verdict.declaration != was.get("declaration", ""))
            learned = (verdict.state in (State.NEW, State.CHANGED) or restated)

            if verdict.is_clear and learned and verdict.body is not None:
                entry = self._facts(verdict)
            elif (verdict.is_clear and verdict.body is not None
                    and carried.get("contract", "ok") != "ok"):
                # The source recovered. Clearing the verdict is not "learning
                # something" -- the facts are unchanged, so they are carried
                # forward -- but leaving it would keep claiming the source is
                # reshaped, and hold it off the conditional path forever on
                # the strength of a failure that is over. Written once, and
                # `broken -> ok` is a diff line worth reading.
                entry = {**carried, "contract": "ok"}
            elif verdict.is_fatal:
                # A dead or reshaped source is worth recording -- the next
                # run reads that verdict before deciding whether a 304 can be
                # believed -- but it has no fingerprint to record, and writing
                # a hash in its place wiped the baseline the comparison uses.
                # The recovery run then reported a change that never happened
                # and deleted a cache for it.
                entry = {**carried, **self._judgement(verdict)}
            else:
                # An `ok` run learned nothing, so it must write nothing: some
                # feeds answer with a different body every time -- Google's
                # version history carries a fresh nextPageToken -- while the
                # value we actually watch is unchanged. Rewriting the hash
                # there would churn the tracked file on every run and destroy
                # the one guarantee it offers, that a diff means something
                # moved. Unreachable and 304 carry forward too.
                entry = carried

            entry["first_seen"] = was.get("first_seen", today)
            if verdict.state is State.CHANGED:
                entry["last_changed"] = today
            elif was.get("last_changed"):
                entry["last_changed"] = was["last_changed"]

            if verdict.consecutive:
                entry[self.FAILING] = self._failing(verdict, today)

            section = (self.CITATIONS
                       if registry.citation(verdict.source_id) is not None
                       else self.SOURCES)
            written[section][verdict.source_id] = entry

        rebuilt: dict[str, Any] = {
            "lock_schema": self.SCHEMA,
            "tool": registry.tool,
            self.SOURCES: dict(sorted(written[self.SOURCES].items())),
        }
        for section in (self.CITATIONS, self.WATCHES):
            if written[section]:
                rebuilt[section] = dict(sorted(written[section].items()))
        return rebuilt

    def _failing(self, verdict: Verdict, today: str) -> dict[str, Any]:
        """The block that appears on an entry only while it is failing, so an
        all-clear run leaves no trace and produces no diff."""

        return {
            "state": verdict.state,
            "consecutive": verdict.consecutive,
            "since": self.failing_since(verdict.source_id) or today,
            "last_error": verdict.error or f"HTTP {verdict.http_status}",
        }

    @staticmethod
    def _judgement(verdict: Verdict) -> dict[str, Any]:
        """What a *failing* run records: the verdict, and nothing else.

        Deliberately not the facts. A failure produced no fingerprint and no
        validator worth keeping, so everything else on the entry is carried
        forward untouched -- the stored fingerprint is the baseline the next
        comparison is made against, and a failure is no reason to lose it.
        """

        entry: dict[str, Any] = {"contract": "broken"}
        if verdict.declaration:
            entry["declaration"] = verdict.declaration
        return entry

    @staticmethod
    def _facts(verdict: Verdict) -> dict[str, Any]:
        """What a run that genuinely learned something records.

        The hash is written only when the source declares no semantic
        fingerprint. Keeping both would imply the comparison uses the hash,
        which it does not -- `Checker._moved` prefers the readable value and
        falls back to the hash only for bodies with no natural scalar.
        """

        entry: dict[str, Any] = {}
        if verdict.now is not None:
            entry["fingerprint"] = verdict.now
        else:
            entry["sha256"] = verdict.sha256
            entry["bytes"] = verdict.bytes_len

        http = {k: v for k, v in (("etag", verdict.etag),
                                  ("last_modified", verdict.last_modified)) if v}
        if http:
            entry["http"] = http
        entry["contract"] = "ok" if not verdict.contract_errors else "broken"
        if verdict.declaration:
            entry["declaration"] = verdict.declaration
        return entry

    def save(self, rebuilt: dict[str, Any]) -> bool:
        """Write only if the content differs. Returns whether it did.

        This is the rule the whole split exists to serve: no diff unless
        something upstream actually moved.
        """

        text = json.dumps(rebuilt, indent=1, ensure_ascii=False, sort_keys=False) + "\n"
        if self.path.is_file() and self.path.read_text(encoding="utf-8") == text:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding="utf-8", newline="\n")
        self.data = json.loads(text)
        return True


# ============================== the state file ==============================

class RunState:
    """`.cache/preflight.state.json`: when the check last ran, and what it did.

    Gitignored and per-machine. Its one job beyond reporting is to let a tool
    notice that preflight has not run lately, which is how the front door
    stays advisory rather than mandatory -- the tool reads a timestamp, it
    does not import anything.
    """

    SCHEMA: ClassVar[int] = 1
    LAST_CHECKED: ClassVar[str] = "last_checked"

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def write(self, *, verdicts: list[Verdict], network: str,
              pruned: list[str], duration_s: float) -> None:
        payload = {
            "state_schema": self.SCHEMA,
            self.LAST_CHECKED: datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "duration_s": round(duration_s, 2),
            "network": network,
            "pruned": pruned,
            "report": [
                {"id": v.source_id, "state": v.state, "ms": v.elapsed_ms,
                 "attempts": v.attempts}
                for v in verdicts
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, indent=1) + "\n", encoding="utf-8", newline="\n")

    def age_days(self) -> float | None:
        """Days since the last check, or None if it has never run."""

        stamp = self.read().get(self.LAST_CHECKED)
        if not stamp:
            return None
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - when).total_seconds() / 86400
