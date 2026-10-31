"""Rendering a check, for a terminal and for a workflow.

Two audiences, one set of facts. The text form is read by whoever just typed
the command, and by whoever opens the scheduled run that failed; the JSON
form carries the same content with none of the formatting, for anything that
wants to post-process a run. The workflow itself needs neither -- the exit
code already says what happened -- which is deliberate: a scheduler that had
to parse a report to learn the outcome would be one parser away from calling
a dead source healthy.

The manual section is the part that earns its length. Some news needs a
person -- a dead source has bespoke handling somebody has to remove, a moved
rule has to be re-read, a watched value means a hand-kept table is out of
date -- and some only needs a rebuild. Every row of the first kind is marked
`[manual]`, and gets an entry saying what happened, what to do and where,
taken from the declarations, so nobody has to remember which is which or go
looking for the file.
"""

from __future__ import annotations as _annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from .enums import STATE_ORDER, Health, State

if TYPE_CHECKING:
    from .models import Action, Registry, Report, Schedule, Verdict

# ============================== text output ==============================


class TextReport:
    """The human form.

    Plain ASCII: this goes into terminals and into a GitHub issue body, and
    both render a fixed-width table reliably.
    """

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
        shown = [v for v in report.sorted_verdicts() if only is None or v.source_id in only]
        # Widened to the longest id present rather than fixed: a ported rule's
        # id is longer than a feed's, and a column that only usually lines up
        # is worse than one that always does.
        width = max([cls.WIDTH, *(len(v.source_id) for v in shown)])
        manual = {v.source_id for v in report.manual}
        return [
            f"  {cls.MARK.get(v.state, '  ')}{v.source_id:<{width}} {v.state:<16} "
            f"{cls.MANUAL if v.source_id in manual else '':<{len(cls.MANUAL) + 1}}"
            f"{cls.detail(v)}".rstrip()
            for v in shown
        ]

    @classmethod
    def detail(cls, verdict: Verdict) -> str:
        if verdict.state is State.CHANGED:
            if verdict.now is not None:
                return f"{verdict.was} -> {verdict.now}"
            return "content changed"
        if verdict.state is State.NEW:
            return "baseline recorded" if verdict.now is None else f"{verdict.now}"
        if verdict.state is State.CONTRACT_BROKEN:
            return "; ".join(verdict.contract_errors) or verdict.error
        if verdict.state in (State.GONE, State.FLAKY):
            runs = f", {verdict.consecutive} consecutive run(s)" if verdict.consecutive > 1 else ""
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
        return [
            f"{'':>{cls.FIELD}}{label:<{cls.LABEL}}{body[0]}",
            # A blank line is kept as a blank line: these values are
            # written as paragraphs and running two of them together is
            # how a careful explanation reads like a wall.
            *(f"{pad}{line}" if line else "" for line in body[1:]),
        ]

    #: Put on every table row that needs a person, and on its entry below.
    MANUAL: ClassVar[str] = "[manual]"
    #: The fields of a manual action, in the order they are printed; the
    #: label is the key with its underscore turned into a space.
    FIELDS: ClassVar[tuple[str, ...]] = (
        "what",
        "do",
        "where",
        "url",
        "cache",
        "on_removal",
        "on_drift",
        "derived",
    )

    @classmethod
    def manual(cls, report: Report, registry: Registry) -> list[str]:
        """Each thing only a person can do: what happened, what to do, and where."""
        items = ManualAction.items(report, registry)
        if not items:
            return ["no manual action needed", ""]
        lines = [f"MANUAL ACTION NEEDED ({len(items)})", ""]
        for item in items:
            lines.append(f"  {cls.MANUAL} {item['id']} -- {item['kind']}")
            for key in cls.FIELDS:
                lines += cls.field(key.replace("_", " "), item.get(key, ""))
            lines.append("")
        return lines

    @classmethod
    def transient(cls, report: Report) -> list[str]:
        lines = [f"PREFLIGHT STOPPED -- {report.tool}", ""]
        for verdict in report.transient:
            lines.append(
                f"  flaky  {verdict.source_id:<{cls.WIDTH}} "
                f"{verdict.error} after {verdict.attempts} attempt(s)"
            )
        lines.append("")
        # One verdict per source. "Not dead, retry" is true of a source that
        # failed once and false of one that has failed run after run, and
        # saying it of both is how a report talks someone into building past
        # a source the exit code already calls dead.
        escalated = {v.source_id for v in report.escalated}
        if any(v.source_id not in escalated for v in report.transient):
            lines += [
                "  a source that failed once is not dead. the cache may well cover it.",
                "  retry, or build from the cache with --allow-flaky.",
                "",
            ]
        if any(v.source_id in escalated for v in report.transient):
            lines += [
                "  a source that keeps failing may be gone for good. building from the",
                "  cache with --allow-flaky still works, but the scheduled check exits 1",
                "  until it answers again or its handling is removed from the tool.",
                "",
            ]
        return lines

    # --- the whole thing --------------------------------------------------

    @classmethod
    def render(
        cls,
        report: Report,
        registry: Registry,
        actions: list[Action] | None = None,
        *,
        dry_run: bool = False,
    ) -> str:
        lines: list[str] = []

        if report.first_run:
            lines += [
                (
                    f"baseline recorded for {report.tool}: "
                    f"{len(report.verdicts)} source(s), nothing to compare against yet."
                ),
                "",
            ]

        ported = {c.id for c in registry.citations}
        lines += [f"sources -- {report.tool}", ""]
        lines += cls.table(
            report,
            only={
                v.source_id
                for v in report.verdicts
                if v.source_id not in ported and v.source_id not in report.watched
            },
        )
        lines.append("")

        if ported:
            # Kept apart from the sources because a failure here means
            # something different: no cache is stale and no feed is gone, a
            # rule the tool reimplemented has moved under it.
            lines += ["ported rules", ""]
            lines += cls.table(report, only=ported)
            lines.append("")

        if report.watched:
            # Apart again, and for the opposite reason: nothing here can
            # break. A line in this table is a decision somebody made by hand
            # that upstream no longer agrees with.
            lines += ["watched values", ""]
            lines += cls.table(report, only=set(report.watched))
            lines.append("")

        if report.network is not Health.OK:
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
            lines += ["cache (dry run -- nothing was changed)" if dry_run else "cache", ""]
            lines += [f"  {action}" for action in actions]
            lines.append("")

        if report.escalated:
            # Dated from the lock, never estimated from the cadence: the rule
            # counts runs, and a run by hand counts as much as a scheduled one,
            # so three runs can be three weeks or one afternoon.
            lines += [
                f"  failing since {v.failing_since or 'this run'}, "
                f"{v.consecutive} runs in a row: {v.source_id}"
                for v in report.escalated
            ]
            lines.append("")

        lines += cls.manual(report, registry)

        if report.fatal:
            lines += [
                f"PREFLIGHT FAILED -- {report.tool}",
                "",
                "  a dead source or a moved rule stops every build until the",
                f"  {cls.MANUAL} entries above are dealt with.",
                "",
            ]
        elif report.transient:
            lines += cls.transient(report)

        return "\n".join(lines)


# ============================ manual actions =============================


class ManualAction:
    """What a person has to change by hand, and where, read off the declarations.

    The report marks these so that nobody has to remember which kind of news
    needs a hand and which a rebuild takes care of. What to do is not written
    here: every declaration already carries it -- `on_drift` on a ported rule,
    `decision` on a watched value, `on_removal` and `consumed_by` on a source
    -- and this only puts it beside what happened and where the change goes.
    The sentences below are the parts no single declaration can know.
    """

    #: A source that is gone, or answers in a shape the tool cannot read.
    DEAD: ClassVar[str] = (
        "a dead source is a code change, not a retry: every source has its own\n"
        "handling in the tool, so it has to be removed by hand, or replaced."
    )
    #: A source that has not answered for ESCALATE_AFTER runs in a row.
    DOWN: ClassVar[str] = (
        "open the url. if it is gone for good, its handling has to be removed by\n"
        "hand; while it is only down, a build from the cache with --allow-flaky works."
    )
    #: A ported rule whose quoted lines are no longer where they were.
    MOVED: ClassVar[str] = (
        "a rule that moved is read, not retried: open the file, find what replaced\n"
        "the quoted lines, and bring the port and the anchors back into step."
    )

    @classmethod
    def items(cls, report: Report, registry: Registry) -> list[dict[str, str]]:
        """One entry per manual action, worst first.

        Every entry has `id`, `kind`, `what`, `do` and `where`; the rest are
        there when the declaration has them.
        """
        out: list[dict[str, str]] = []
        for verdict in report.manual:
            entry = {"id": verdict.source_id, "what": TextReport.detail(verdict)}
            if citation := registry.citation(verdict.source_id):
                entry |= {
                    "kind": "ported rule",
                    "do": cls.MOVED,
                    "where": citation.ported_to,
                    "url": citation.url,
                    "on_drift": citation.on_drift,
                }
            elif watch := registry.watch(verdict.source_id):
                entry |= {
                    "kind": "watched value",
                    "do": watch.decision,
                    "where": watch.used_by,
                    "url": watch.url,
                }
            else:
                source = registry.source(verdict.source_id)
                entry |= {"kind": "source", "do": cls.DEAD if verdict.is_fatal else cls.DOWN}
                if source is not None:
                    derived = [d.id for d in registry.derived if source.id in d.derives_from]
                    entry |= {
                        "where": source.consumed_by,
                        "url": source.target,
                        "cache": f".cache/{source.cache}" if source.cache else "",
                        "on_removal": source.on_removal,
                        "derived": ", ".join(derived),
                    }
            out.append(entry)
        return out


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
    def build(
        cls,
        report: Report,
        registry: Registry,
        actions: list[Action] | None = None,
        *,
        schedule: Schedule | None = None,
    ) -> dict[str, Any]:
        return {
            "report_schema": cls.SCHEMA,
            "tool": report.tool,
            "first_run": report.first_run,
            "network": report.network,
            "may_proceed": report.may_proceed(),
            "escalate_after": report.ESCALATE_AFTER,
            "ported": [c.id for c in registry.citations],
            #: What that count is worth in days, so a reader of the JSON can
            #: interpret it without opening the tool's schedule.
            "cadence_days": schedule.every_days if schedule else None,
            "escalated": [v.source_id for v in report.escalated],
            "manual": ManualAction.items(report, registry),
            "counts": {
                state: sum(1 for v in report.verdicts if v.state == state)
                for state in STATE_ORDER
                if any(v.state is state for v in report.verdicts)
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
                {"verb": a.verb, "cache": a.cache, "reason": a.reason, "target": a.target}
                for a in (actions or [])
            ],
            "watched": sorted(report.watched),
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
    def render(
        cls,
        report: Report,
        registry: Registry,
        actions: list[Action] | None = None,
        *,
        schedule: Schedule | None = None,
    ) -> str:
        return json.dumps(cls.build(report, registry, actions, schedule=schedule), indent=1)
