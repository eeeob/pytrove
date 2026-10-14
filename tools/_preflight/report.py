"""Rendering a check, for a terminal and for a workflow.

Two audiences, one set of facts. The text form is read by whoever just typed
the command, and by whoever opens the scheduled run that failed; the JSON
form carries the same content with none of the formatting, for anything that
wants to post-process a run. The workflow itself needs neither -- the exit
code already says what happened -- which is deliberate: a scheduler that had
to parse a report to learn the outcome would be one parser away from calling
a dead source healthy.

The failure report is the part that earns its length. A dead source cannot be
retried or worked around: every source has bespoke handling in the tool that
reads it, so somebody has to remove that code. The report therefore prints
where the source is consumed and what its loss costs, both declared in the
registry, so the person reading it does not have to go looking.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from .check import Report
from .janitor import Action
from .model import Registry, Schedule, State, Verdict

# ============================== text output ==============================

class TextReport:
    """The human form. Plain ASCII: this goes into terminals and into a
    GitHub issue body, and both render a fixed-width table reliably."""

    #: One mark per state, so a long table can be skimmed by column.
    MARK: ClassVar[dict[str, str]] = {
        State.OK: "  ",
        State.NEW: "+ ",
        State.CHANGED: "~ ",
        State.FLAKY: "? ",
        State.GONE: "! ",
        State.CONTRACT_BROKEN: "! ",
    }
    WIDTH: ClassVar[int] = 22

    # --- the table --------------------------------------------------------

    @classmethod
    def table(cls, report: Report, only: set[str] | None = None) -> list[str]:
        shown = [v for v in report.sorted_verdicts()
                 if only is None or v.source_id in only]
        # Widened to the longest id present rather than fixed: a ported rule's
        # id is longer than a feed's, and a column that only usually lines up
        # is worse than one that always does.
        width = max([cls.WIDTH, *(len(v.source_id) for v in shown)])
        return [
            f"  {cls.MARK.get(v.state, '  ')}{v.source_id:<{width}} "
            f"{v.state:<16} {cls.detail(v)}".rstrip()
            for v in shown
        ]

    @classmethod
    def detail(cls, verdict: Verdict) -> str:
        if verdict.state == State.CHANGED:
            if verdict.now is not None:
                return f"{verdict.was} -> {verdict.now}"
            return "content changed"
        if verdict.state == State.NEW:
            return "baseline recorded" if verdict.now is None else f"{verdict.now}"
        if verdict.state == State.CONTRACT_BROKEN:
            return "; ".join(verdict.contract_errors) or verdict.error
        if verdict.state in (State.GONE, State.FLAKY):
            runs = (f", {verdict.consecutive} consecutive run(s)"
                    if verdict.consecutive > 1 else "")
            return f"{verdict.error}{runs}"
        return ""

    # --- the failure report -----------------------------------------------

    #: Indent of a field's value, so a wrapped paragraph lines up under it
    #: instead of running back to the margin. The registry's prose is written
    #: across several lines on purpose and this is where it gets read.
    FIELD: ClassVar[int] = 6
    LABEL: ClassVar[int] = 14

    @classmethod
    def field(cls, label: str, value: str) -> list[str]:
        """One label and its value, every continuation line aligned under it."""

        body = [line.strip() for line in (value or "").strip().splitlines()]
        if not body:
            return []
        pad = " " * (cls.FIELD + cls.LABEL)
        return [f"{'':>{cls.FIELD}}{label:<{cls.LABEL}}{body[0]}",
                *(f"{pad}{line}" for line in body[1:] if line)]

    @classmethod
    def failure(cls, report: Report, registry: Registry) -> list[str]:
        """Everything a developer needs in order to act, and nothing else."""

        lines = [f"PREFLIGHT FAILED -- {report.tool}", ""]

        for verdict in report.fatal:
            citation = registry.citation(verdict.source_id)
            source = citation.as_source() if citation else registry.source(
                verdict.source_id)
            lines.append(f"  {verdict.state}  {verdict.source_id}")
            lines += cls.field("detail", cls.detail(verdict))
            if citation:
                # A moved rule is not a dead source and the two call for
                # opposite things: nothing has to be removed, something has
                # to be re-read and the port brought back into step.
                lines += cls.field("url", citation.url)
                lines += cls.field("ported to", citation.ported_to)
                lines += cls.field("on drift", citation.on_drift)
                lines.append("")
                continue
            if source:
                lines += cls.field("url", source.target)
                if source.cache:
                    lines += cls.field("cache", f".cache/{source.cache}")
                lines += cls.field("consumed by", source.consumed_by)
                lines += cls.field("on removal", source.on_removal)
                dependents = [d.id for d in registry.derived
                              if verdict.source_id in d.derives_from]
                if dependents:
                    lines += cls.field("derived", ", ".join(dependents))
            lines.append("")

        if any(registry.citation(v.source_id) for v in report.fatal):
            lines += [
                "  a rule that moved is read, not retried: open the file, find what",
                "  replaced the quoted lines, and bring the port and the anchors",
                "  back into step. until then the generator would keep emitting",
                "  strings the client itself no longer produces.",
                "",
            ]
        if any(not registry.citation(v.source_id) for v in report.fatal):
            lines += [
                "  a dead source is a code change, not a retry: every source has",
                "  its own handling in the tool, so it has to be removed by hand.",
                "",
            ]
        return lines

    @classmethod
    def transient(cls, report: Report) -> list[str]:
        lines = [f"PREFLIGHT STOPPED -- {report.tool}", ""]
        for verdict in report.transient:
            lines.append(f"  flaky  {verdict.source_id:<{cls.WIDTH}} "
                         f"{verdict.error} after {verdict.attempts} attempt(s)")
        lines += [
            "",
            "  these are not dead sources. the cache may well cover them.",
            "  retry, or build from the cache with --allow-flaky.",
            "",
        ]
        return lines

    # --- the whole thing --------------------------------------------------

    @classmethod
    def render(cls, report: Report, registry: Registry,
               actions: list[Action] | None = None,
               *, dry_run: bool = False,
               schedule: Schedule | None = None) -> str:
        lines: list[str] = []

        if report.first_run:
            lines += [
                f"baseline recorded for {report.tool}: "
                f"{len(report.verdicts)} source(s), nothing to compare against yet.",
                "",
            ]

        ported = {c.id for c in registry.citations}
        lines += [f"sources -- {report.tool}", ""]
        lines += cls.table(report, only={v.source_id for v in report.verdicts
                                         if v.source_id not in ported})
        lines.append("")

        if ported:
            # Kept apart from the sources because a failure here means
            # something different: no cache is stale and no feed is gone, a
            # rule the tool reimplemented has moved under it.
            lines += ["ported rules", ""]
            lines += cls.table(report, only=ported)
            lines.append("")

        if report.network != "ok":
            lines += [
                f"  network: {report.network} -- more than half the sources could",
                "  not be reached, so this says more about the runner than about",
                "  the sources. nothing is escalated.",
                "",
            ]

        if actions:
            # In a dry run the verbs describe what *would* happen, and
            # the heading has to say so: "deleted play_devices.csv" is
            # otherwise a plain statement that a 5 MB download is gone.
            lines += ["cache (dry run -- nothing was changed)" if dry_run
                      else "cache", ""]
            lines += [f"  {action}" for action in actions]
            lines.append("")

        if report.deferred:
            carried = ", ".join(f"{k} x{n}" for k, n in sorted(report.deferred.items()))
            lines += [f"  (registry also declares {carried}, "
                      f"not checked by this phase)", ""]

        if report.escalated:
            named = ", ".join(v.source_id for v in report.escalated)
            # The rule counts runs because a run is the only thing it can
            # count, but nobody thinks in runs: at a weekly cadence three of
            # them is three weeks, and that is the sentence a reader can act
            # on. Without a declared schedule the count stands on its own.
            runs = f"{report.ESCALATE_AFTER}+ runs"
            if schedule is not None:
                runs += (f", about {report.ESCALATE_AFTER * schedule.every_days}"
                         f" days at this tool's cadence")
            lines += [f"  failing every run for {runs}: {named}", ""]

        if report.fatal:
            lines += cls.failure(report, registry)
        elif report.transient:
            lines += cls.transient(report)

        return "\n".join(lines)


# ============================== json output ==============================

class JsonReport:
    """The machine form.

    Flat and explicit: it carries the counters and the declared prose rather
    than a table, so anything keeping a history of runs has the facts without
    having to read formatting. Nothing in this repository consumes it -- the
    scheduled workflow decides on the exit code alone -- so it is an output,
    not an interface, and may grow a key without a migration.
    """

    SCHEMA: ClassVar[int] = 1

    @classmethod
    def build(cls, report: Report, registry: Registry,
              actions: list[Action] | None = None,
              *, schedule: Schedule | None = None) -> dict[str, Any]:
        return {
            "report_schema": cls.SCHEMA,
            "tool": report.tool,
            "first_run": report.first_run,
            "network": report.network,
            "may_proceed": report.may_proceed(),
            "escalate_after": report.ESCALATE_AFTER,
            "ported": [c.id for c in registry.citations],
            #: What that count is worth in days, so a reader of the JSON can
            #: interpret it without knowing the workflow's cron.
            "cadence_days": schedule.every_days if schedule else None,
            "escalated": [v.source_id for v in report.escalated],
            "counts": {
                state: sum(1 for v in report.verdicts if v.state == state)
                for state in State.ORDER
                if any(v.state == state for v in report.verdicts)
            },
            "sources": [
                {
                    "id": v.source_id,
                    "state": v.state,
                    "was": v.was,
                    "now": v.now,
                    "http_status": v.http_status,
                    "error": v.error,
                    "contract_errors": list(v.contract_errors),
                    "consecutive": v.consecutive,
                    "attempts": v.attempts,
                    "elapsed_ms": v.elapsed_ms,
                    **cls._declared(registry, v.source_id),
                }
                for v in report.sorted_verdicts()
            ],
            "cache": [
                {"kind": a.kind, "cache": a.cache, "reason": a.reason,
                 "target": a.target}
                for a in (actions or [])
            ],
            "deferred": report.deferred,
        }

    @staticmethod
    def _declared(registry: Registry, source_id: str) -> dict[str, Any]:
        source = registry.source(source_id)
        if source is None:
            return {}
        return {
            "url": source.target,
            "cache": source.cache,
            "on_change": source.on_change,
            "consumed_by": source.consumed_by,
            "on_removal": source.on_removal,
        }

    @classmethod
    def render(cls, report: Report, registry: Registry,
               actions: list[Action] | None = None,
               *, schedule: Schedule | None = None) -> str:
        return json.dumps(cls.build(report, registry, actions,
                                    schedule=schedule), indent=1)
